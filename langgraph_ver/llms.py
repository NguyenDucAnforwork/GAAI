import os
import time
from dotenv import load_dotenv, find_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage

# Check for OpenAI-only flag
USE_OPENAI_ONLY = os.getenv("USE_OPENAI_ONLY", "").upper() == "TRUE"

load_dotenv(find_dotenv(), override=True)

# Initialize OpenAI LLM
openai_llm = ChatOpenAI(
    model="gpt-4o-mini", 
    api_key=os.getenv("OPENAI_API_KEY"),
    temperature=0.1,
    streaming=False,  # Turn off streaming to avoid issues
    max_retries=2,
    request_timeout=60,
)

# Only import Gemini if not in OpenAI-only mode
if not USE_OPENAI_ONLY:
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        # Configure Gemini as fallback only
        gemini_llm = ChatGoogleGenerativeAI(
            model="gemini-1.5-flash", 
            google_api_key=os.getenv("GOOGLE_API_KEY"),
            temperature=0.1,
            convert_system_message_to_human=False,
        )
    except:
        # If import fails, create a mock
        print("Failed to import Gemini - OpenAI will be used for all requests")
        gemini_llm = None
else:
    print("Running in OpenAI-only mode - Gemini will not be used")
    gemini_llm = None

# langgraph_ver/llms.py

from langchain_openai import ChatOpenAI

# Model "Nhanh" (Rẻ) cho các agent chuyên môn
def get_fast_llm():
    """Trả về LLM nhanh và rẻ, như gpt-4o-mini."""
    return ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0.0,
        max_tokens=4000,
        # stream=True # Cân nhắc bật stream nếu muốn
    )

# Model "Thông minh" (Đắt) cho Manager, Reasoner, và Verifier
def get_smart_llm():
    """Trả về LLM thông minh nhất, như gpt-4o."""
    return ChatOpenAI(
        model="gpt-4o-mini",  # Use mini model with zero temperature for precision
        temperature=0.0,      # Zero temperature for deterministic reasoning
        max_tokens=4000,
        # stream=True
    )

def get_llm(provider: str = "openai") -> BaseChatModel:
    """Get the appropriate LLM based on provider name with OpenAI as default"""
    # In OpenAI-only mode, always return OpenAI regardless of requested provider
    if USE_OPENAI_ONLY:
        return openai_llm
        
    if provider.lower() == "openai":
        return openai_llm
    elif provider.lower() in ["gemini", "google"] and gemini_llm:
        return gemini_llm
    else:
        # Default to OpenAI
        return openai_llm

def call_llm(state, llm=None):
    """Call the LLM with the current state information"""
    # In OpenAI-only mode, always use OpenAI
    if USE_OPENAI_ONLY:
        llm = openai_llm
    elif llm is None:
        llm = openai_llm
        
    messages = state.get("messages", [])
    
    try:
        response = llm.invoke(messages)
        return {"messages": messages + [response]}
    except Exception as e:
        print(f"Error calling LLM: {str(e)}")
        # Return error message
        error_msg = AIMessage(content=f"Sorry, I encountered an error: {str(e)}")
        return {"messages": messages + [error_msg]}
