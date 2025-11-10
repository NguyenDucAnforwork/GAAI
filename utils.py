#@title ===== Helper Functions =====
from typing import Dict
import inspect
import json

def _is_tool_result_empty_or_failed(result: str | None) -> bool:
    """Kiểm tra xem kết quả từ tool có rỗng hoặc chứa lỗi không."""
    if result is None:
        return True
    
    result_lower = result.strip().lower()
    if not result_lower:
        return True
        
    # Thêm các từ khóa báo lỗi phổ biến
    error_keywords = ["error", "failed", "not found", "unable to", "could not", "no result"]
    if any(keyword in result_lower for keyword in error_keywords):
        return True
        
    return False

def _extract_text(obj) -> str:
    """Extract text from various llama-index response types"""
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj
    
    # Try common attributes
    for attr in ("response", "output", "result", "text", "content"):
        try:
            val = getattr(obj, attr, None)
            if isinstance(val, str) and val:
                return val
            if hasattr(val, "content") and isinstance(val.content, str):
                return val.content
            if hasattr(val, "text") and isinstance(val.text, str):
                return val.text
        except:
            continue
    
    # Try message attribute
    try:
        if hasattr(obj, "message"):
            msg = obj.message
            if hasattr(msg, "content") and isinstance(msg.content, str):
                return msg.content
    except:
        pass
    
    return str(obj)

async def _acomplete_safe(llm, prompt: str) -> str:
    """Safe LLM completion with fallback"""
    try:
        if hasattr(llm, "acomplete") and inspect.iscoroutinefunction(llm.acomplete):
            resp = await llm.acomplete(prompt)
            return getattr(resp, "text", str(resp))
    except Exception:
        pass
    
    # Fallback to sync
    resp = llm.complete(prompt)
    return getattr(resp, "text", str(resp))

async def _arun_agent(agent, prompt: str):
    """Run agent with various calling methods"""
    if hasattr(agent, "run"):
        try:
            res = await agent.run(prompt)
            if inspect.isawaitable(res):
                res = await res
            return res
        except Exception:
            pass
    
    if hasattr(agent, "achat"):
        try:
            return await agent.achat(prompt)
        except Exception:
            pass
    
    if hasattr(agent, "chat"):
        try:
            return agent.chat(prompt)
        except Exception:
            pass
    
    raise RuntimeError(f"Agent {type(agent)} does not expose a compatible run/chat API.")

def _select_tool_rule_based(query: str, context: str, agents_dict: Dict[str, object]) -> tuple:
    """Rule-based tool selection with reasoning"""
    combined = f"{query} {context}".lower()
    
    # DOI/Academic papers
    if any(k in combined for k in ["doi", "10.", "arxiv", "paper", "journal", "endnote", "citation"]):
        if "web_agent" in agents_dict:
            return "web_agent", "Need to search for academic content with DOI or paper information"
    
    # Real estate/Property data
    if any(k in combined for k in ["sold", "home", "house", "property", "real estate", "price", "address"]):
        if "web_agent" in agents_dict:
            return "web_agent", "Need to search for real estate/property sales data"
    
    # Web search needed
    if any(k in combined for k in ["search", "find", "lookup", "wikipedia", "google", "web"]):
        if "web_agent" in agents_dict:
            return "web_agent", "Need to perform web search for information"
    
    # Math/Calculations
    if any(k in combined for k in ["calculate", "derivative", "solve", "equation", "math"]) or re.search(r"\d.*[\+\-\*/]", combined):
        if "compute_agent" in agents_dict:
            return "compute_agent", "Need to perform mathematical calculations"
    
    # File operations
    if any(k in combined for k in [".pdf", ".csv", ".xlsx", "file", "document", "read"]):
        if "read_agent" in agents_dict:
            return "read_agent", "Need to read or process file content"
    
    # Image operations
    if any(k in combined for k in ["image", "photo", "ocr", ".jpg", ".png"]):
        if "vlm_agent" in agents_dict:
            return "vlm_agent", "Need to process image or visual content"
    
    # Audio/Video
    if any(k in combined for k in ["audio", "video", "transcribe", ".mp4", ".wav"]):
        if "av_agent" in agents_dict:
            return "av_agent", "Need to process audio or video content"
    
    # Default to managed agent
    return "managed_agent", "Using general-purpose agent for complex reasoning"