import streamlit as st
from datetime import datetime
from typing import Optional, List, Dict, Any
from supabase import create_client, Client

@st.cache_resource
def get_supabase() -> Client:
    return create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_KEY"]
    )

def db() -> Client:
    return get_supabase()

# === Message Functions ===

def add_message(user_id: str, role: str, content: str, thinking: Optional[str], timestamp: str) -> int:
    result = db().table("koedy_messages").insert({
        "user_id": user_id,
        "role": role,
        "content": content,
        "thinking": thinking,
        "timestamp": timestamp
    }).execute()
    return result.data[0]["id"] if result.data else 0

def get_messages(user_id: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    query = db().table("koedy_messages").select("*").eq("user_id", user_id).order("id", desc=False)

    if limit:
        count_result = db().table("koedy_messages").select("id", count="exact").eq("user_id", user_id).execute()
        total = count_result.count or 0

        if total > limit:
            query = db().table("koedy_messages").select("*").eq("user_id", user_id).order("id", desc=True).limit(limit)
            result = query.execute()
            return list(reversed([{
                "id": row["id"],
                "role": row["role"],
                "content": row["content"],
                "thinking": row["thinking"],
                "timestamp": row["timestamp"]
            } for row in result.data])) if result.data else []

    result = query.execute()
    return [{
        "id": row["id"],
        "role": row["role"],
        "content": row["content"],
        "thinking": row["thinking"],
        "timestamp": row["timestamp"]
    } for row in result.data] if result.data else []

def get_message_count(user_id: str) -> int:
    result = db().table("koedy_messages").select("id", count="exact").eq("user_id", user_id).execute()
    return result.count or 0

def get_oldest_messages(user_id: str, count: int) -> List[Dict[str, Any]]:
    result = db().table("koedy_messages").select("*").eq("user_id", user_id).order("id", desc=False).limit(count).execute()
    return [{
        "id": row["id"],
        "role": row["role"],
        "content": row["content"],
        "thinking": row["thinking"],
        "timestamp": row["timestamp"]
    } for row in result.data] if result.data else []

def delete_messages_by_ids(ids: List[int]):
    for msg_id in ids:
        db().table("koedy_messages").delete().eq("id", msg_id).execute()

# === Summary Functions ===

def add_summary(user_id: str, turn_start: int, turn_end: int, summary_text: str) -> int:
    result = db().table("koedy_summaries").insert({
        "user_id": user_id,
        "turn_start": turn_start,
        "turn_end": turn_end,
        "summary_text": summary_text
    }).execute()
    return result.data[0]["id"] if result.data else 0

def get_recent_summaries(user_id: str, limit: int = 2) -> List[Dict[str, Any]]:
    result = db().table("koedy_summaries").select("*").eq("user_id", user_id).eq("archived", False).order("id", desc=True).limit(limit).execute()
    if not result.data:
        return []
    rows = list(reversed(result.data))
    return [{
        "id": row["id"],
        "turn_start": row["turn_start"],
        "turn_end": row["turn_end"],
        "summary_text": row["summary_text"],
        "created_at": row["created_at"]
    } for row in rows]

def get_total_turns_summarized(user_id: str) -> int:
    result = db().table("koedy_summaries").select("turn_end").eq("user_id", user_id).order("id", desc=True).limit(1).execute()
    if result.data:
        return result.data[0]["turn_end"]
    return 0

def get_non_archived_summary_count(user_id: str) -> int:
    result = db().table("koedy_summaries").select("id").eq("user_id", user_id).eq("archived", False).execute()
    return len(result.data) if result.data else 0

def get_oldest_non_archived_summary(user_id: str):
    result = db().table("koedy_summaries").select("*").eq("user_id", user_id).eq("archived", False).order("id").limit(1).execute()
    return result.data[0] if result.data else None

def mark_summary_archived(summary_id: int):
    db().table("koedy_summaries").update({"archived": True}).eq("id", summary_id).execute()

# === Ancient History Functions ===

def get_ancient_history(user_id: str) -> List[Dict[str, Any]]:
    result = db().table("koedy_ancient_history").select("*").eq("user_id", user_id).order("id").execute()
    return result.data if result.data else []

def add_ancient_history_entry(user_id: str, turn_range: str, content: str):
    db().table("koedy_ancient_history").insert({
        "user_id": user_id,
        "turn_range": turn_range,
        "content": content
    }).execute()

# === Extended History Functions ===

def archive_messages(user_id: str, messages: List[Dict[str, Any]], summary_id: int):
    for msg in messages:
        db().table("koedy_extended_history").insert({
            "user_id": user_id,
            "summary_id": summary_id,
            "role": msg["role"],
            "content": msg["content"],
            "thinking": msg.get("thinking"),
            "timestamp": msg["timestamp"]
        }).execute()

def search_extended_history(user_id: str, query: str, limit: int = 20) -> List[Dict[str, Any]]:
    result = db().table("koedy_extended_history").select(
        "id, role, content, thinking, timestamp, summary_id"
    ).eq("user_id", user_id).or_(
        f"content.ilike.%{query}%,thinking.ilike.%{query}%"
    ).order("id", desc=True).limit(limit).execute()

    if not result.data:
        return []

    summary_ids = list(set(row["summary_id"] for row in result.data if row["summary_id"]))
    summaries = {}
    if summary_ids:
        sum_result = db().table("koedy_summaries").select("id, turn_start, turn_end").in_("id", summary_ids).execute()
        if sum_result.data:
            summaries = {s["id"]: s for s in sum_result.data}

    return [{
        "id": row["id"],
        "role": row["role"],
        "content": row["content"],
        "thinking": row["thinking"],
        "timestamp": row["timestamp"],
        "turn_start": summaries.get(row["summary_id"], {}).get("turn_start"),
        "turn_end": summaries.get(row["summary_id"], {}).get("turn_end")
    } for row in result.data]

# === Notes Functions ===

def get_note(user_id: str, note_type: str) -> Optional[Dict[str, Any]]:
    result = db().table("koedy_notes").select("*").eq("user_id", user_id).eq("note_type", note_type).execute()
    if result.data:
        row = result.data[0]
        return {
            "id": row["id"],
            "type": note_type,
            "content": row["content"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"]
        }
    return None

def set_note(user_id: str, note_type: str, content: str):
    now = datetime.now().isoformat()
    existing = get_note(user_id, note_type)
    if existing:
        db().table("koedy_notes").update({
            "content": content,
            "updated_at": now
        }).eq("user_id", user_id).eq("note_type", note_type).execute()
    else:
        db().table("koedy_notes").insert({
            "user_id": user_id,
            "note_type": note_type,
            "content": content,
            "created_at": now,
            "updated_at": now
        }).execute()

def get_all_notes(user_id: str) -> Dict[str, Optional[Dict[str, Any]]]:
    return {
        "active": get_note(user_id, "active"),
        "ongoing": get_note(user_id, "ongoing"),
        "permanent": get_note(user_id, "permanent")
    }

def clear_note(user_id: str, note_type: str) -> bool:
    if note_type == "permanent":
        return False
    result = db().table("koedy_notes").delete().eq("user_id", user_id).eq("note_type", note_type).execute()
    return bool(result.data)

# === Metadata / Turn Counter Functions ===

def get_turn_counter(user_id: str) -> int:
    result = db().table("koedy_metadata").select("value").eq("key", f"turn_counter_{user_id}").execute()
    if result.data:
        return int(result.data[0]["value"])
    return 0

def increment_turn_counter(user_id: str) -> int:
    current = get_turn_counter(user_id)
    new_val = current + 1
    result = db().table("koedy_metadata").update({
        "value": str(new_val)
    }).eq("key", f"turn_counter_{user_id}").execute()
    if not result.data:
        db().table("koedy_metadata").insert({
            "key": f"turn_counter_{user_id}",
            "value": str(new_val)
        }).execute()
    return new_val

# === Token Cost Calc ===

def log_token_usage(user_id: str, call_type: str, input_tokens: int, output_tokens: int, input_cost: float, output_cost: float, total_cost: float):
    db().table("koedy_token_usage").insert({
        "user_id": user_id,
        "call_type": call_type,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "input_cost": input_cost,
        "output_cost": output_cost,
        "total_cost": total_cost
    }).execute()

def get_user_total_usage(user_id: str) -> Dict[str, Any]:
    result = db().table("koedy_token_usage").select("*").eq("user_id", user_id).execute()
    if not result.data:
        return {"input_tokens": 0, "output_tokens": 0, "total_cost": 0.0}

    total_in = sum(r["input_tokens"] for r in result.data)
    total_out = sum(r["output_tokens"] for r in result.data)
    total_cost = sum(float(r["total_cost"]) for r in result.data)

    return {
        "input_tokens": total_in,
        "output_tokens": total_out,
        "total_cost": round(total_cost, 4)
    }

# === Export Functions ===

def export_all_data(user_id: str) -> Dict[str, Any]:
    messages = get_messages(user_id)
    sum_result = db().table("koedy_summaries").select("*").eq("user_id", user_id).order("id", desc=False).execute()
    summaries = sum_result.data if sum_result.data else []
    ancient = get_ancient_history(user_id)
    return {
        "messages": messages,
        "summaries": summaries,
        "ancient_history": ancient,
        "notes": get_all_notes(user_id),
        "turn_counter": get_turn_counter(user_id),
        "exported_at": datetime.now().isoformat()
    }