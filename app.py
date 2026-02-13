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
    get_turn_counter,
    log_token_usage,
    get_user_total_usage,
    get_spending_limit
)
import base64
st.set_page_config(page_icon="logo.png", page_title="Koedy", layout="wide")

def set_background(image_file, opacity=0.50):
    with open(image_file, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    st.markdown(f"""
    <style>
    /* Background image */
    .stApp {{
        background-image: url("data:image/png;base64,{data}");
        background-size: contain;
        background-position: center top;
        background-attachment: fixed;
        background-repeat: no-repeat;
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
    /* NEW: Mobile padding */
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
 - Use freely/whimsically as a scratchpad, not as a rigid tracker, for temporary context (up to a week or so; no rigid timeframe constraint), casual thoughts, current focus, etc. (500 word limit)
 - For medium-term (50+ Turns) context (tracking projects or other topic threads), things to watch for or "keep in mind" - include current status and tags to search for in the future when deeper context is needed (1000 word limit)  
 - Will NOT be deleted - maximize information per token here especially - use (sparingly) for relationship milestones, significant moments, achievements, important events, etc - (2000 word limit)
These notes persist across conversations and remain in future context (but are hidden from the user), allowing you to track threads over time, including mapping your own uncertainty or confidence. Update them when user provides new or corrective information that you want to remember for future context or when context shifts or something important happens.
"""

    return base_prompt

# MODIFIED: Now injects turn numbers and timestamps into message content for API
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

    # NEW: Error handling for summary API call
    try:
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
    except Exception as e:
        st.toast(f"⚠️ Summary generation failed — will retry next cycle")
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

    # NEW: Error handling for compression API call
    try:
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
    except Exception as e:
        st.toast(f"⚠️ Compression failed — will retry next cycle")
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

            if not summary_text:  # NEW: Skip if summary generation failed
                return False

            # Save summary
            summary_id = add_summary(user_id, turn_start, turn_end, summary_text)

            # Archive messages to extended history
            summary_entry = {
                "role": "system",
                "content": f"[SUMMARY of turns {turn_start}-{turn_end}]\n{summary_text}",
                "thinking": None,
                "timestamp": datetime.now(PT).strftime("%Y-%m-%d %H:%M:%S")
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