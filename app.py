import streamlit as st
from datetime import datetime, timedelta, timezone
PT = timezone(timedelta(hours=-8))
from anthropic import Anthropic
import pdfplumber
from io import BytesIO
import json
import re
import requests
from bs4 import BeautifulSoup
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
    get_non_archived_summary_count,
    get_oldest_non_archived_summary,
    mark_summary_archived,
    get_ancient_history,
    add_ancient_history_entry,
    search_extended_history,
    get_all_notes,
    set_note,
    clear_note,
    export_all_data,
    increment_turn_counter,
    decrement_turn_counter,
    get_turn_counter,
    log_token_usage,
    get_user_total_usage,
    get_spending_limit
)
import base64
st.set_page_config(page_icon="logo.png", page_title="Koedy", layout="wide")

def set_background(image_file, opacity=0.80):
    with open(image_file, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    overlay = 1 - opacity  # higher overlay = more faded image
    st.markdown(f"""
    <style>
    .stApp {{
        background-image: 
            linear-gradient(rgba(10, 15, 25, {overlay}), rgba(10, 15, 25, {overlay})),
            url("data:image/png;base64,{data}");
        background-size: cover, contain;
        background-position: center, center top;
        background-attachment: fixed, fixed;
        background-repeat: no-repeat, no-repeat;
    }}
    /* User bubbles */
    [data-testid="stChatMessage"]:has([aria-label="Chat message from user"]) {{
        background-color: rgba(8, 145, 178, 0.12);
        border-left: 3px solid #0891B2;
        border-radius: 8px;
        padding: 8px 12px;
        margin-bottom: 8px;
    }}
    /* Koedy bubbles */
    [data-testid="stChatMessage"]:has([aria-label="Chat message from assistant"]) {{
        background-color: rgba(22, 32, 50, 0.7);
        border-left: 3px solid #2A3F5F;
        border-radius: 8px;
        padding: 8px 12px;
        margin-bottom: 8px;
    }}
    /* Tagline captions */
    .stCaption, [data-testid="stCaptionContainer"] {{
        color: #badeff !important;
    }}
    /* Placeholder text visible */
    [data-testid="stChatInputTextArea"]::placeholder {{
        color: #0891B2 !important;
    }}
    /* Submit arrow teal */
    [data-testid="stChatInputSubmitButton"] svg {{
        color: #0891B2 !important;
    }}
    /* Submit button background */
    [data-testid="stChatInputSubmitButton"] {{
        background-color: #2A3F5F !important;
        border: none !important;
    }}
    /* Chat input text - light mode */
    @media (prefers-color-scheme: light) {{
        [data-testid="stChatInputTextArea"] {{
            color: #E0F2FE !important;
        }}
    }}
    .stSpinner > div {{
    font-style: italic;
    }}
    .stChatMessage caption, .stChatMessage .stCaption p {{
    text-align: right;
    }}
        /* Sidebar buttons match theme */
    [data-testid="stSidebar"] button {{
        background-color: rgba(22, 32, 50, 0.7) !important;
        color: #badeff !important;
        border: 1px solid #2A3F5F !important;
        font-size: 0.85em !important;
        padding: 4px 8px !important;
    }}
    [data-testid="stSidebar"] button:hover {{
        background-color: rgba(8, 145, 178, 0.3) !important;
        border-color: #0891B2 !important;
    }}
        /* Mobile padding */
    @media (max-width: 768px) {{
        .stApp {{
            background-position: center 90px !important;
        }}
    }}
    @media (max-width: 768px) {{
        .main .block-container {{
            padding-left: 1rem;
            padding-right: 1rem;
        }}
        [data-testid="stChatMessage"] {{
            padding: 6px 8px;
            margin-bottom: 6px;
        }}
    }}
    </style>
    """, unsafe_allow_html=True)
set_background("link_photo.png")
# Opus pricing per token (dollars/tokens)
INPUT_COST_PER_TOKEN = 5.00 / 1_000_000
OUTPUT_COST_PER_TOKEN = 25.00 / 1_000_000

# Initialize client
client = Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])

# Access codes — add friends here as: "their_code": "their_name"
ACCESS_CODES = json.loads(st.secrets["ACCESS_CODES"])

# === ACCESS GATE ===
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

    # Add ancient history
    ah_entries = get_ancient_history(user_id)
    if ah_entries:
        ah_section = "\n\n=== Ancient Conversation History ===\n"
        for entry in ah_entries:
            ah_section += f"\n{entry['turn_range']}:\n{entry['content']}\n"
        base_prompt += ah_section

    # Add recent summaries
    summaries = get_recent_summaries(user_id, limit=2)
    if summaries:
        summary_section = "\n\n=== EXTENDED CONVERSATION HISTORY ===\n"
        for s in summaries:
            summary_section += f"\nTurns {s['turn_start']}-{s['turn_end']} Summary:\n{s['summary_text']}\n"
        base_prompt += summary_section

    # Add notes
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
You have access to three note types you can update by including these tags in your response. You have full permission to use and utilize these at your discretion on when to update as you see fit to ensure ideal collaboration between yourself and the user; YOU get to decide when to add/edit these.
[ACTIVE NOTE: your content here] - Use freely/whimsically as a scratchpad, not as a rigid tracker, for temporary context (up to a week or so; no rigid timeframe constraint), casual thoughts, current focus, etc. (500 word limit)
[ONGOING NOTE: your content here] - For medium-term (50+ Turns) context (tracking projects or other topic threads), things to watch for or "keep in mind" - include current status and tags to search for in the future when deeper context is needed (1000 word limit)  
[PERMANENT NOTE: your content here] - Will NOT be deleted - maximize information per token here especially - use (sparingly) for relationship milestones, significant moments, achievements, important events, etc - (2000 word limit)
These notes persist across conversations and remain in future context (but are hidden from the user), allowing you to track threads over time, including mapping your own uncertainty or confidence. Update them when user provides new or corrective information that you want to remember for future context or when context shifts or something important happens.
"""

    return base_prompt

def format_messages_for_api(messages: list, current_turn: int) -> list:
    """Format messages with temporal context so Koedy can track time and turns."""
    formatted = []
    user_count = sum(1 for m in messages if m["role"] == "user")
    first_user_turn = max(1, current_turn - user_count + 1)

    turn = first_user_turn
    for msg in messages:
        ts = msg.get("timestamp", "")
        if msg["role"] == "user":
            prefix = f"[Turn {turn} | {ts}] " if ts else f"[Turn {turn}] "
            formatted.append({"role": "user", "content": prefix + msg["content"]})
            turn += 1
        else:
            prefix = f"[{ts}] " if ts else ""
            formatted.append({"role": "assistant", "content": prefix + msg["content"]})
    return formatted

def generate_summary(user_id: str, messages_to_summarize: list, turn_start: int, turn_end: int) -> str:
    """Generate a summary of messages using a hidden API call."""
    base_prompt = load_system_prompt()

    summary_prompt = f"""Summarize this conversation segment (Turns {turn_start}-{turn_end}). Begin your summary with the turn range.

Prioritize user calibration above all else. This summary exists so Koedy can know and serve this user better over time.

Extract and preserve:
- Who the user is: personality traits, values, communication style, humor, depth preference
- What matters to them: ongoing life situations, relationships, stressors, goals, interests
- Emotional patterns: what affects them, how they process, what support looks like for them
- Interaction dynamics: what works well, what falls flat, how they respond to different approaches
- Ongoing threads: unresolved topics, commitments made, things to follow up on

Guidelines:
- Weight relational and emotional context over technical minutiae; who the user IS matters more than what they asked about
- Do not significantly overlap with previous summaries; reference ongoing threads but add new context rather than restating
- Include context tags: simple labels [creative, technical, personal, emotional, etc.]
- Maximize information per token; no markdown (this summary is for your own context, not the user)
- Do not exceed 250 words unless critical calibration information would be lost"""

    # Fetch previous summaries for context threading
    prev_summaries = get_recent_summaries(user_id, limit=2)

    # Build content with previous summary context
    content = ""
    if prev_summaries:
        content += "Previous summaries for context continuity (do not repeat — use to connect threads and reduce overlap):\n\n"
        for s in prev_summaries:
            content += f"Turns {s['turn_start']}-{s['turn_end']}: {s['summary_text']}\n\n"
        content += "---\n\n"

    content += "New conversation segment to summarize:\n\n"
    for msg in messages_to_summarize:
        role = "User" if msg["role"] == "user" else "Koedy"
        content += f"{role}: {msg['content']}\n\n"

    content += "\n\n" + summary_prompt

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=5000,
        system=base_prompt,
        thinking={
            "type": "enabled",
            "budget_tokens": 3500
        },
        messages=[{
            "role": "user",
            "content": content
        }]
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

def compress_summary_to_ah(user_id: str, summary: dict) -> str:
    """Compress a summary into ancient history bullet points."""
    base_prompt = load_system_prompt()

    compression_prompt = """Compress the following conversation summary into 1-4 concise bullet points for long-term ancient history storage. Use fewer when the conversation segment is straightforward; use more only when significant calibration details would be lost.

Preserve only what matters for ongoing calibration with this user:
- Key discoveries about who they are
- Significant emotional moments or relationship developments
- Decisions or commitments that affect future conversations
- Context that would be lost without preservation

Be extremely concise. Maximize information per token. No markdown. Each bullet should be one substantive line starting with a dash."""

    content = f"Summary of Turns {summary['turn_start']}-{summary['turn_end']}:\n{summary['summary_text']}\n\n{compression_prompt}"

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=2000,
        system=base_prompt,
        thinking={
            "type": "enabled",
            "budget_tokens": 2000
        },
        messages=[{
            "role": "user",
            "content": content
        }]
    )

    usage = response.usage
    in_tokens = usage.input_tokens
    out_tokens = usage.output_tokens
    in_cost = in_tokens * INPUT_COST_PER_TOKEN
    out_cost = out_tokens * OUTPUT_COST_PER_TOKEN
    log_token_usage(user_id, "compression", in_tokens, out_tokens, in_cost, out_cost, in_cost + out_cost)

    for block in response.content:
        if block.type == "text":
            return block.text
    return ""

def check_and_summarize(user_id: str):
    """Check if we need to summarize and do it."""
    count = get_message_count(user_id)

    if count >= 100:  # 50 turns = 100 messages
        oldest_messages = get_oldest_messages(user_id, 50)  # 25 turns = 50 messages

        if oldest_messages:
            # Calculate turn numbers first (needed for summary prompt)
            total_summarized = get_total_turns_summarized(user_id)
            turn_start = total_summarized + 1
            turn_end = total_summarized + 25

            # Generate summary with turn range context
            summary_text = generate_summary(user_id, oldest_messages, turn_start, turn_end)

            # Save summary
            summary_id = add_summary(user_id, turn_start, turn_end, summary_text)

            # Archive messages to extended history
            summary_entry = {
                "role": "system",
                "content": f"[SUMMARY of turns {turn_start}-{turn_end}]\n{summary_text}",
                "thinking": None,
                "timestamp": datetime.now(PT).strftime("%A %Y-%m-%d %H:%M:%S")
            }
            archive_messages(user_id, oldest_messages + [summary_entry], summary_id)

            # Delete from active messages
            ids_to_delete = [msg["id"] for msg in oldest_messages]
            delete_messages_by_ids(ids_to_delete)

            # Check if summaries need compression to AH
            non_archived_count = get_non_archived_summary_count(user_id)
            while non_archived_count > 2:
                oldest = get_oldest_non_archived_summary(user_id)
                if oldest:
                    ah_content = compress_summary_to_ah(user_id, oldest)
                    turn_range = f"Turns {oldest['turn_start']}-{oldest['turn_end']}"
                    add_ancient_history_entry(user_id, turn_range, ah_content)
                    mark_summary_archived(oldest['id'])
                    non_archived_count -= 1
                else:
                    break

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

def extract_urls(text):
    return re.findall(r'https?://[^\s<>"{}|\\^`\[\]]+', text)

def fetch_page_text(url, char_limit=5000):
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        return soup.get_text(separator="\n", strip=True)[:char_limit]
    except Exception:
        return None

def enrich_message_with_urls(text):
    urls = extract_urls(text)
    if not urls:
        return text
    enriched = text
    for url in urls[:3]:
        page_text = fetch_page_text(url)
        if page_text:
            enriched += f"\n\n[Content from {url}]:\n{page_text}"
    return enriched

def call_koedy(user_id, context_depth, is_resend=False):
    """Make API call and handle response. Extracted so resend can reuse it."""
    # Check spending limit
    usage_data = get_user_total_usage(user_id)
    spending_limit = get_spending_limit(user_id)
    if usage_data["total_cost"] >= spending_limit:
        with st.chat_message("assistant", avatar="logo.png"):
            st.write("You've reached your current message limit! Reach out to Koyote to continue. 🐾")
        return

    # Summarize if needed
    with st.spinner("Getting to know you better..."):
        summarized = check_and_summarize(user_id)
    if summarized:
        st.toast("✨ Memory updated")

    full_system_prompt = build_full_system_prompt()
    db_messages = get_messages(user_id, limit=context_depth * 2)
    api_messages = format_messages_for_api(db_messages, get_turn_counter(user_id))
    
    # Enrich last message with any URL content
    if api_messages and api_messages[-1]["role"] == "user":
        api_messages[-1]["content"] = enrich_message_with_urls(api_messages[-1]["content"])

    # Handle pending file attachment
    attachment = st.session_state.get("pending_attachment")
    if attachment and api_messages and api_messages[-1]["role"] == "user":
        if attachment["type"] == "image":
            text_content = api_messages[-1]["content"]
            api_messages[-1]["content"] = [
                {"type": "image", "source": {
                    "type": "base64",
                    "media_type": attachment["media_type"],
                    "data": attachment["base64"]
                }},
                {"type": "text", "text": text_content}
            ]
        elif attachment["type"] == "pdf":
            api_messages[-1]["content"] += f"\n\n[Content from {attachment['filename']}]:\n{attachment['text']}"

        st.session_state.last_sent_file = attachment["file_key"]
        st.session_state.pop("pending_attachment", None)
    
    with st.chat_message("assistant", avatar="logo.png"):
        try:
            with st.spinner("Koedy is ruminating..."):
                response = client.messages.create(
                    model="claude-opus-4-6",
                    max_tokens=16000,
                    thinking={"type": "enabled", "budget_tokens": 10000},
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

            u = response.usage
            in_cost = u.input_tokens * INPUT_COST_PER_TOKEN
            out_cost = u.output_tokens * OUTPUT_COST_PER_TOKEN
            log_token_usage(user_id, "message", u.input_tokens, u.output_tokens, in_cost, out_cost, in_cost + out_cost)

            clean_response = process_note_tags(response_text)
            add_message(user_id, "assistant", clean_response, thinking_text, response_timestamp)

            st.session_state.display_messages.append({
                "role": "assistant",
                "content": clean_response,
                "thinking": thinking_text,
                "timestamp": response_timestamp
            })

            st.write(clean_response)
            st.markdown(f'<p style="text-align: right; font-size: 0.75em; color: #385480;">{response_timestamp}</p>', unsafe_allow_html=True)

        except Exception:
            st.warning("Something went wrong — try sending your message again. 🐾")
            if not is_resend and st.session_state.display_messages and st.session_state.display_messages[-1]["role"] == "user":
                st.session_state.display_messages.pop()
                recent = get_messages(user_id, limit=1)
                if recent and recent[0]["role"] == "user":
                    delete_messages_by_ids([recent[0]["id"]])

# === STREAMLIT UI ===

st.title("Koedy")

# Initialize display messages
if "display_messages" not in st.session_state:
    st.session_state.display_messages = get_messages(user_id)

# Sidebar
with st.sidebar:
    st.header(f"Welcome, {user_id}")
    st.caption("I get to know you,")
    st.caption("Not just your questions:")
    st.caption("The more you share, the better I understand")

    st.divider()
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

    st.header("Last message:")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("↻ Resend", use_container_width=True):
            if st.session_state.display_messages and st.session_state.display_messages[-1]["role"] == "assistant":
                st.session_state.display_messages.pop()
                recent = get_messages(user_id, limit=1)
                if recent and recent[0]["role"] == "assistant":
                    delete_messages_by_ids([recent[0]["id"]])
            st.session_state.needs_resend = True
            st.rerun()
    with col2:
        if st.button("✕ Delete", use_container_width=True):
            recent = get_messages(user_id, limit=2)
            if recent:
                delete_messages_by_ids([m["id"] for m in recent])
                for _ in range(min(2, len(st.session_state.display_messages))):
                    if st.session_state.display_messages:
                        st.session_state.display_messages.pop()
                decrement_turn_counter(user_id)
            st.rerun()

    st.divider()

    st.caption("Attach file:")
    uploaded_file = st.file_uploader(
        "Upload",
        type=["png", "jpg", "jpeg", "gif", "webp", "pdf"],
        label_visibility="collapsed"
    )
    if uploaded_file:
        file_key = f"{uploaded_file.name}_{uploaded_file.size}"
        if file_key != st.session_state.get("last_sent_file"):
            file_bytes = uploaded_file.read()
            file_type = uploaded_file.type

            if file_type == "application/pdf":
                try:
                    with pdfplumber.open(BytesIO(file_bytes)) as pdf:
                        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
                    st.session_state.pending_attachment = {
                        "type": "pdf",
                        "text": text[:10000],
                        "filename": uploaded_file.name,
                        "file_key": file_key
                    }
                    st.caption(f"📎 {uploaded_file.name} ready")
                except Exception:
                    st.caption("⚠️ Couldn't read PDF")
            else:
                b64 = base64.b64encode(file_bytes).decode()
                st.session_state.pending_attachment = {
                    "type": "image",
                    "base64": b64,
                    "media_type": file_type,
                    "filename": uploaded_file.name,
                    "file_key": file_key
                }
                st.caption(f"📎 {uploaded_file.name} ready")
        else:
            st.caption(f"📎 {uploaded_file.name} sent ✓")

    st.caption("Koedy only sees files while attached", help="Remove file(s) when you're done — adds cost each turn attached")

    st.divider()

    st.caption("Search history:")
    search_query = st.text_input("Search", label_visibility="collapsed", placeholder="Search past conversations...")
    if search_query:
        results = search_extended_history(user_id, search_query)
        if results:
            for r in results:
                role = "You" if r["role"] == "user" else "Koedy"
                preview = r["content"][:200].replace("\n", " ")
                st.markdown(f"**{role}:** {preview}...")
        else:
            st.caption("Nothing found — try different terms 🐾")
        
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
        with st.chat_message("user", avatar="chat_logo.png"):
            st.write(msg["content"])
            if msg.get("timestamp"):
                st.markdown(f'<p style="text-align: right; font-size: 0.75em; color: #385480;">{msg["timestamp"]}</p>', unsafe_allow_html=True)
    else:
        with st.chat_message("assistant", avatar="logo.png"):
            st.write(msg["content"])
            if msg.get("timestamp"):
                st.markdown(f'<p style="text-align: right; font-size: 0.75em; color: #385480;">{msg["timestamp"]}</p>', unsafe_allow_html=True)

# Action buttons are in sidebar

# Handle resend
if st.session_state.get("needs_resend"):
    st.session_state.needs_resend = False
    call_koedy(user_id, context_depth, is_resend=True)
    st.rerun()
# Chat input
user_messages = [m for m in st.session_state.display_messages if m["role"] == "user"]

if st.session_state.get("user_id") == "Anthropic" and len(user_messages) >= 10:
    st.chat_input("I bet you wanted to send an 11th 😏", disabled=True)
elif user_input := st.chat_input("Hey there! Name's Koedy. What's on your mind?"):
    turn_number = increment_turn_counter(user_id)
    user_timestamp = datetime.now(PT).strftime("%A %H:%M:%S %Y-%m-%d")
    turn_display.write(f"Turn: {turn_number}")

    add_message(user_id, "user", user_input, None, user_timestamp)

    st.session_state.display_messages.append({
        "role": "user",
        "content": user_input,
        "timestamp": user_timestamp
    })

    with st.chat_message("user", avatar="chat_logo.png"):
        st.write(user_input)
        st.markdown(f'<p style="text-align: right; font-size: 0.75em; color: #385480;">{user_timestamp}</p>', unsafe_allow_html=True)

    call_koedy(user_id, context_depth)