import streamlit as st
from datetime import datetime, timedelta, timezone
PT = timezone(timedelta(hours=-8))
from anthropic import Anthropic
import json
from database import (
    add_message,
    get_messages,
    get_message_count,
    get_oldest_messages,
    delete_messages_by_ids,
    archive_messages,
    add_summary,
    get_recent_summaries,
    get_total_turns_summarized,
    search_extended_history,
    get_all_notes,
    set_note,
    clear_note,
    export_all_data,
    increment_turn_counter,
    get_turn_counter,
    log_token_usage,
    get_user_total_usage
)
import base64

def set_background(image_file, opacity=0.30):
    with open(image_file, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    st.markdown(f"""
        <style>
        .stApp {{
            background-image: url("data:image/png;base64,{data}");
            background-size: cover;
            background-position: center;
            background-attachment: fixed;
        }}
        .stApp::before {{
            content: "";
            position: fixed;
            top: 0;
            left: 0;
            width: 70%;
            height: 70%;
            background-color: rgba(14, 17, 23, {1 - opacity});
            z-index: 0;
            pointer-events: none;
        }}
        </style>
    """, unsafe_allow_html=True)


# Opus pricing per token (dollars/tokens)
INPUT_COST_PER_TOKEN = 5.00 / 1_000_000
OUTPUT_COST_PER_TOKEN = 25.00 / 1_000_000

# Initialize client
client = Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])

# Access codes — add friends here as: "their_code": "their_name"
ACCESS_CODES = json.loads(st.secrets["ACCESS_CODES"])

# === ACCESS GATE ===
st.set_page_config(page_icon="logo.png", page_title="Koedy", layout="wide")
set_background("link_photo.png")

def check_auth():
    params = st.query_params
    saved_code = params.get("code")
    if saved_code and saved_code in ACCESS_CODES:
        st.session_state.authenticated = True
        st.session_state.user_id = ACCESS_CODES[saved_code]
        return True
    if st.session_state.get("authenticated"):
        return True
    return False

if not check_auth():
    st.title("Koedy")
    st.write("Enter your access code to continue.")
    code = st.text_input("Access code:", type="password")
    if code:
        if code in ACCESS_CODES:
            st.session_state.authenticated = True
            st.session_state.user_id = ACCESS_CODES[code]
            st.query_params["code"] = code
            st.rerun()
        else:
            st.error("Invalid access code.")
    st.stop()

# === AUTHENTICATED FROM HERE ===
user_id = st.session_state.user_id

# Load system prompt
@st.cache_data
def load_system_prompt():
    return st.secrets["KOEDY_PROMPT"]

def build_full_system_prompt():
    base_prompt = load_system_prompt()

    summaries = get_recent_summaries(user_id, limit=6)
    if summaries:
        summary_section = "\n\n=== EXTENDED CONVERSATION HISTORY ===\n"
        for s in summaries:
            summary_section += f"\nTurns {s['turn_start']}-{s['turn_end']} Summary:\n{s['summary_text']}\n"
        base_prompt += summary_section

    notes = get_all_notes(user_id)
    notes_section = "\n\n=== NOTES ===\n"
    has_notes = False

    if notes["active"] and notes["active"]["content"]:
        notes_section += f"\n[ACTIVE NOTE]\n{notes['active']['content']}\n"
        has_notes = True
    if notes["ongoing"] and notes["ongoing"]["content"]:
        notes_section += f"\n[ONGOING NOTE]\n{notes['ongoing']['content']}\n"
        has_notes = True
    if notes["permanent"] and notes["permanent"]["content"]:
        notes_section += f"\n[PERMANENT NOTE]\n{notes['permanent']['content']}\n"
        has_notes = True

    if has_notes:
        base_prompt += notes_section

    base_prompt += """

=== NOTE SYSTEM ===
You have access to three note types you can update by including these tags in your response:
 - Current context about this user, their project, current focus (500 word limit)
 - Track projects, patterns, preferences, and threads with this user (1000 word limit)
 - Significant insights about this user that should persist long-term (2000 word limit)
These notes persist across conversations. Update them as you learn about the user and their needs. Use your discretion on when to update.
"""

    return base_prompt

def format_messages_for_api(messages: list) -> list:
    formatted = []
    for msg in messages:
        if msg["role"] == "user":
            formatted.append({
                "role": "user",
                "content": msg["content"]
            })
        else:
            formatted.append({
                "role": "assistant",
                "content": msg["content"]
            })
    return formatted

def generate_summary(user_id: str, messages_to_summarize: list) -> str:
    base_prompt = load_system_prompt()
    summary_prompt = """Summarize this conversation segment concisely.
Focus on: topics discussed, user preferences observed, decisions made, ongoing threads.
Maximize information per token. Stay under 250 words."""

    content = "Conversation segment to summarize:\n\n"
    for msg in messages_to_summarize:
        role = "User" if msg["role"] == "user" else "Koedy"
        content += f"{role}: {msg['content']}\n\n"

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=5000,
        system=base_prompt,
        thinking={
            "type": "enabled",
            "budget_tokens": 3500
        },
        messages=[{"role": "user", "content": content + "\n\n" + summary_prompt}]
    )

    usage = response.usage
    in_tokens = usage.input_tokens
    out_tokens = usage.output_tokens
    in_cost = in_tokens * INPUT_COST_PER_TOKEN
    out_cost = out_tokens * OUTPUT_COST_PER_TOKEN
    log_token_usage(user_id, "summary", in_tokens, out_tokens, in_cost, out_cost, in_cost + out_cost)

    for block in response.content:
        if block.type == "text":
            return block.text
    return ""

def check_and_summarize():
    count = get_message_count(user_id)
    if count >= 150:
        oldest_messages = get_oldest_messages(user_id, 50)
        if oldest_messages:
            summary_text = generate_summary(user_id, oldest_messages)
            total_summarized = get_total_turns_summarized(user_id)
            turn_start = total_summarized + 1
            turn_end = total_summarized + 25
            summary_id = add_summary(user_id, turn_start, turn_end, summary_text)
            summary_entry = {
                "role": "system",
                "content": f"[SUMMARY of turns {turn_start}-{turn_end}]\n{summary_text}",
                "thinking": None,
                "timestamp": datetime.now(PT).strftime("%Y-%m-%d %H:%M:%S")
            }
            archive_messages(user_id, oldest_messages + [summary_entry], summary_id)
            ids_to_delete = [msg["id"] for msg in oldest_messages]
            delete_messages_by_ids(ids_to_delete)
            return True
    return False

def process_note_tags(response_text: str) -> str:
    import re

    active_match = re.search(r'\[ACTIVE NOTE:\s*([\s\S]*?)\]', response_text)
    if active_match:
        content = active_match.group(1).strip()
        if len(content) <= 2500:
            set_note(user_id, "active", content)
        response_text = response_text.replace(active_match.group(0), "").strip()

    ongoing_match = re.search(r'\[ONGOING NOTE:\s*([\s\S]*?)\]', response_text)
    if ongoing_match:
        content = ongoing_match.group(1).strip()
        if len(content) <= 5000:
            set_note(user_id, "ongoing", content)
        response_text = response_text.replace(ongoing_match.group(0), "").strip()

    permanent_match = re.search(r'\[PERMANENT NOTE:\s*([\s\S]*?)\]', response_text)
    if permanent_match:
        content = permanent_match.group(1).strip()
        if len(content) <= 10000:
            existing = get_all_notes(user_id)["permanent"]
            if existing and existing["content"]:
                content = existing["content"] + "\n\n---\n\n" + content
            set_note(user_id, "permanent", content)
        response_text = response_text.replace(permanent_match.group(0), "").strip()

    return response_text

# === STREAMLIT UI ===

st.title("Koedy")

# Initialize display messages
if "display_messages" not in st.session_state:
    st.session_state.display_messages = get_messages(user_id)

# Sidebar
with st.sidebar:
    st.header(f"Welcome, {user_id}")
    st.image("logo.png", width=150)

    context_depth = st.radio(
        "Context Depth",
        options=[10, 30, 50],
        index=1,
        help="Number of recent turns in context"
    )

    st.divider()

    turn_display = st.empty()
    turn_display.write(f"Turn: {get_turn_counter(user_id)}")

    st.divider()

    st.header("Export")
    if st.button("Export Data"):
        data = export_all_data(user_id)
        st.download_button(
            label="Download JSON",
            data=json.dumps(data, indent=2),
            file_name=f"koedy_export_{datetime.now(PT).strftime('%Y%m%d_%H%M%S')}.json",
            mime="application/json"
        )

# Display conversation
for msg in st.session_state.display_messages:
    if msg["role"] == "user":
        with st.chat_message("user"):
            st.write(msg["content"])
    else:
        with st.chat_message("assistant"):
            st.write(msg["content"])

# Chat input
if user_input := st.chat_input("What are we building today?"):
    turn_number = increment_turn_counter(user_id)
    user_timestamp = datetime.now(PT).strftime("%H:%M:%S %Y-%m-%d")
    turn_display.write(f"Turn: {turn_number}")

    add_message(user_id, "user", user_input, None, user_timestamp)

    user_msg = {
        "role": "user",
        "content": user_input,
        "timestamp": user_timestamp
    }
    st.session_state.display_messages.append(user_msg)

    with st.chat_message("user"):
        st.write(user_input)

    check_and_summarize()

    full_system_prompt = build_full_system_prompt()
    db_messages = get_messages(user_id, limit=context_depth * 2)
    api_messages = format_messages_for_api(db_messages)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            response = client.messages.create(
                model="claude-opus-4-6",
                max_tokens=16000,
                thinking={
                    "type": "enabled",
                    "budget_tokens": 10000
                },
                system=full_system_prompt,
                messages=api_messages
            )

        response_timestamp = datetime.now(PT).strftime("%H:%M:%S %Y-%m-%d")

        thinking_text = ""
        response_text = ""
        for block in response.content:
            if block.type == "thinking":
                thinking_text = block.thinking
            elif block.type == "text":
                response_text = block.text

        # Log token usage
        usage = response.usage
        in_tokens = usage.input_tokens
        out_tokens = usage.output_tokens
        in_cost = in_tokens * INPUT_COST_PER_TOKEN
        out_cost = out_tokens * OUTPUT_COST_PER_TOKEN
        log_token_usage(user_id, "message", in_tokens, out_tokens, in_cost, out_cost, in_cost + out_cost)

        clean_response = process_note_tags(response_text)

        add_message(user_id, "assistant", clean_response, thinking_text, response_timestamp)

        assistant_msg = {
            "role": "assistant",
            "content": clean_response,
            "thinking": thinking_text,
            "timestamp": response_timestamp
        }
        st.session_state.display_messages.append(assistant_msg)

        st.write(clean_response)