import asyncio
from typing import Dict, List, Any, Optional, TypedDict
from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from enum import Enum

from langchain_core.agents import AgentAction, AgentFinish, AgentStep

from .llms import get_llm, get_smart_llm, get_formatter_llm
from .agents.web_agent import run_web_agent
try:
    from langgraph_ver.agents.video_agent_smolvlm import create_video_analysis_agent, extract_youtube_url
except Exception:
    def create_video_analysis_agent():
        return None
    def extract_youtube_url(text):
        import re
        m = re.search(r'(https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)[\w-]+)', text)
        return m.group(1) if m else None
from .agents.reasoning_agent import run_reasoning_agent
from .agents.creative_agent import run_creative_agent
from .agents.math_agent import run_math_agent
from .prompts import GAAI_WORKFLOW_SYSTEM_PROMPT

import os as _os

# Langfuse tracing is optional; disable with LANGFUSE_DISABLED=true to avoid
# per-call network overhead (e.g. during batch evaluation).
if _os.getenv("LANGFUSE_DISABLED", "").lower() == "true":
    langfuse_handler = None
else:
    try:
        from langfuse.langchain import CallbackHandler
        langfuse_handler = CallbackHandler()
    except Exception as _e:
        print(f"[workflow] Langfuse disabled: {_e}")
        langfuse_handler = None

_CALLBACKS = [langfuse_handler] if langfuse_handler else []

import re
import uuid

class AgentType(str, Enum):
    """Type of agent to use for the current query"""
    WEB = "web"
    VIDEO = "video"
    REASONING = "reasoning"
    MATH = "math"
    CREATIVE = "creative"
    GENERAL = "general"

class WorkflowState(TypedDict):
    """State for the OptimizedGAAIWorkflow"""
    messages: List[Any]
    agent_type: Optional[AgentType]
    intermediate_steps: list[tuple[AgentAction, str]]
    query: str
    response: Optional[str]

def create_optimized_gaai_workflow():
    """
    Create the optimized General AI Agent workflow
    
    Returns:
        A compiled langgraph workflow for integrated agent capabilities
    """
    # Define the nodes for the workflow
    def router(state: WorkflowState) -> Dict:
        """Determine which agent type to use based on the query"""
        query = state["query"]
        messages = state.get("messages", [])
        
        print(f"🧠 Router analyzing query: {query[:100]}...")
        
        # Enhanced system instructions for better routing
        router_system_prompt = """You are an intelligent task router for a multi-agent system.
        Your job is to analyze user queries and route them to the most appropriate specialist agent.
        
        AGENT CAPABILITIES:
        
        🔍 WEB: 
        - Real-time information lookup
        - Current events, news, weather
        - Factual data that changes over time
        - Information from specific websites
        - When query mentions "according to Wikipedia" or other sources
        
        🎥 VIDEO:
        - Analysis of YouTube videos
        - Questions about video content
        - When query contains YouTube URLs (youtube.com or youtu.be)
        - Counting objects, animals, people in videos
        - Describing video scenes or content
        
        🧠 REASONING:
        - Logic puzzles and riddles
        - Probability and game theory problems
        - Strategic thinking and analysis
        - Multi-step logical reasoning
        - Understanding complex rules and patterns
        - Decision analysis (e.g., "which option is best?")
        
        🧮 MATH:
        - Pure numerical calculations (5+5, 2*3)
        - Solving equations (2x+3=7)
        - Unit conversions when straightforward
        - Simple arithmetic word problems
        - NOT for complex logic puzzles or probability reasoning
        
        🎨 CREATIVE:
        - Writing stories, poems, scripts
        - Creative brainstorming and ideas
        - Artistic descriptions
        - Content generation
        
        💬 GENERAL:
        - Simple conversations
        - General knowledge questions
        - Explanations of concepts
        - Other tasks not fitting above categories
        
        ANALYSIS GUIDELINES:
        1. For YOUTUBE VIDEO ANALYSIS: If query contains YouTube URL (youtube.com, youtu.be), choose VIDEO
        2. For LOGIC PUZZLES, RIDDLES, PROBABILITY: Choose REASONING (even if numbers are involved)
        3. For pure CALCULATIONS (5+5, distance=speed*time): Choose MATH
        4. For looking up FACTS or CURRENT DATA: Choose WEB
        5. For CREATIVE WRITING: Choose CREATIVE
        6. When in doubt between MATH and REASONING: If the problem requires understanding complex rules or patterns, choose REASONING
        
        Respond with EXACTLY one word: VIDEO, WEB, REASONING, MATH, CREATIVE, or GENERAL
        """
        
        router_prompt = f"""
        Query to analyze: "{query}"
        
        This query appears to involve:
        - YouTube video analysis? (Look for: "youtube.com", "youtu.be", video URLs)
        - Logic puzzle or riddle? (Look for: "riddle", "puzzle", "which should you choose", game rules, probability)
        - Pure mathematical calculations? (Look for: "calculate", "solve equation", simple arithmetic)
        - Web search needs? (Look for: "according to Wikipedia", current information, factual lookup)
        - Creative content generation? (Look for: writing, story, poem requests)
        - General conversation? (Simple questions, explanations)
        
        CRITICAL PRIORITY:
        1. If the query contains YouTube URLs (youtube.com or youtu.be), choose VIDEO
        2. If the query describes a game, puzzle, or scenario requiring strategic thinking, choose REASONING not MATH
        
        Select the MOST appropriate agent type.
        """
        
        # Create messages for routing
        routing_messages = [
            SystemMessage(content=router_system_prompt),
            HumanMessage(content=router_prompt)
        ]
        
        # Use the primary chat LLM for routing decisions
        llm = get_llm()
        model_name = getattr(llm, "model", None) or getattr(llm, "model_name", "llm")
        print(f"🔄 Using {model_name} for routing decision...")
        
        response = llm.invoke(routing_messages)
        decision_text = response.content.strip().upper()
        
        print(f"🤖 Router LLM response: '{decision_text}'")
        
        # Extract decision with better logic - prioritize VIDEO first
        if "VIDEO" in decision_text:
            agent_type = AgentType.VIDEO
        elif "WEB" in decision_text:
            agent_type = AgentType.WEB
        elif "MATH" in decision_text:
            agent_type = AgentType.MATH
        elif "CREATIVE" in decision_text:
            agent_type = AgentType.CREATIVE
        elif "REASONING" in decision_text:
            agent_type = AgentType.REASONING
        else:
            agent_type = AgentType.GENERAL
        
        print(f"🎯 Final routing decision: {agent_type}")
        
        return {
            "messages": messages,
            "agent_type": agent_type, 
            "query": query
        }
    
    async def web_agent_node(state: WorkflowState) -> Dict:
        """Process query using web agent"""
        query = state["query"]

        try:
            # Run web agent with timeout to prevent hanging
            response = await asyncio.wait_for(
                run_web_agent_with_retry(query), 
                timeout=60.0  # Set a reasonable timeout
            )
        except asyncio.TimeoutError:
            response = "I'm sorry, the web search took too long to complete. Please try a simpler query."
        except Exception as e:
            print(f"Error in web agent: {str(e)}")
            response = f"I encountered an issue while searching for information: {str(e)}"
            
        return {
            **state,
            "response": response
        }
    
    async def video_agent_node(state: WorkflowState) -> Dict:
        """Process query using Gemini's native YouTube video understanding."""
        query = state["query"]

        try:
            youtube_url = extract_youtube_url(query)
            if not youtube_url:
                return {**state, "response": "❌ No YouTube URL found in the query."}

            print(f"🎥 Analyzing YouTube video with Gemini: {youtube_url}")

            def _analyze():
                from langchain_google_genai import ChatGoogleGenerativeAI
                from langgraph_ver.llms import GEMINI_KEYS
                msg = HumanMessage(content=[
                    {"type": "media", "file_uri": youtube_url, "mime_type": "video/mp4"},
                    {"type": "text", "text": (
                        f"{query}\n\nWatch the video and answer precisely. "
                        "End with 'FINAL ANSWER: <answer>'."
                    )},
                ])
                # The Gemini free-tier quota is scarce; try every unique key once
                # until one succeeds (this is the only Gemini call in the pipeline).
                last_err = None
                for key in dict.fromkeys(GEMINI_KEYS):
                    try:
                        llm = ChatGoogleGenerativeAI(
                            model="gemini-2.5-flash",
                            google_api_key=key,
                            temperature=0.0,
                            max_output_tokens=2048,
                            max_retries=1,
                        )
                        return llm.invoke([msg]).content
                    except Exception as e:
                        last_err = e
                        continue
                raise last_err or RuntimeError("No Gemini key succeeded")

            response = await asyncio.wait_for(asyncio.to_thread(_analyze), timeout=90.0)

        except asyncio.TimeoutError:
            response = "The video analysis timed out."
        except Exception as e:
            print(f"Error in video agent: {str(e)}")
            response = f"❌ Video agent error: {str(e)}"

        return {**state, "response": response}
    
    async def run_web_agent_with_retry(query: str, max_attempts: int = 3) -> str:  
        """  
        Run web agent with multiple attempts for academic papers  
        """  
        for attempt in range(max_attempts):  
            try:  
                result = await run_web_agent(query)  
                
                # Kiểm tra nếu kết quả không đầy đủ  
                if "not available" in result.lower() or "could not find" in result.lower():  
                    if attempt < max_attempts - 1:  
                        # Thử lại với query đơn giản hơn  
                        continue  
                
                return result  
                
            except Exception as e:  
                if attempt == max_attempts - 1:  
                    raise  
                continue  
        
        return "Could not retrieve information after multiple attempts"
    
    async def reasoning_agent_node(state: WorkflowState) -> Dict:
        """Process query using reasoning agent"""
        query = state["query"]
        
        try:
            # Run reasoning agent with extended timeout for complex problems
            response = await asyncio.wait_for(
                run_reasoning_agent(query),
                timeout=180.0  # 3 minutes for complex reasoning
            )
        except asyncio.TimeoutError:
            response = "The reasoning process timed out. The problem may be too complex for the current time limit."
        except Exception as e:
            print(f"Error in reasoning agent: {str(e)}")
            response = f"Error in reasoning agent: {str(e)}"
        
        return {
            **state,
            "response": response
        }
    
    async def math_agent_node(state: WorkflowState) -> Dict:
        """Process query using math agent"""
        query = state["query"]
        
        try:
            # Run math agent with timeout
            response = await asyncio.wait_for(
                run_math_agent(query),
                timeout=60.0
            )
        except asyncio.TimeoutError:
            response = "I'm sorry, solving this math problem took too long. Please try a simpler problem."
        except Exception as e:
            print(f"Error in math agent: {str(e)}")
            response = f"I encountered an issue while solving this math problem: {str(e)}"
        
        return {
            **state,
            "response": response
        }
    
    async def creative_agent_node(state: WorkflowState) -> Dict:
        """Process query using creative agent"""
        query = state["query"]
        
        try:
            # Run creative agent with timeout
            response = await asyncio.wait_for(
                run_creative_agent(query),
                timeout=60.0
            )
        except asyncio.TimeoutError:
            response = "I'm sorry, generating creative content took too long. Please try a simpler request."
        except Exception as e:
            print(f"Error in creative agent: {str(e)}")
            response = f"I encountered an issue while generating creative content: {str(e)}"
        
        return {
            **state,
            "response": response
        }
    
    def general_agent_node(state: WorkflowState) -> Dict:
        """Process query using general LLM capabilities"""
        query = state["query"]
        messages = state.get("messages", [])
        
        # Add system message if not already there
        if not any(isinstance(m, SystemMessage) for m in messages):
            messages = [SystemMessage(content=GAAI_WORKFLOW_SYSTEM_PROMPT)]
        
        # Add the user query
        messages.append(HumanMessage(content=query))
        
        # Get response from LLM
        llm = get_llm("openai")
        response = llm.invoke(messages)
        
        return {
            **state,
            "response": response.content,
            "messages": messages + [response]
        }
    
    def format_response(state: WorkflowState) -> Dict:
        """
        STRICT formatter using prompt only.
        - Feed (question + raw response) to a small formatter prompt.
        - Expect EXACTLY one line "FINAL ANSWER: <value>" from the model.
        - Then extract the substring after "FINAL ANSWER:" (case-insensitive) with simple string ops.
        """
        raw = state.get("response") or ""
        query = state.get("query") or ""
        agent_type = state.get("agent_type", AgentType.GENERAL)
        messages = state.get("messages", [])

        print(f"📝 Raw response before formatting: {raw}")
        print(f"📝 Agent type: {agent_type}")
        print(f"📝 Messages history: {[type(m) for m in messages]}")

        # 1) Call a dedicated formatter LLM (kept on gpt-4o-mini for a reliable
        #    output contract).
        llm = get_formatter_llm()
        system_msg = SystemMessage(content=(
            "You are a strict answer formatter for the GAIA benchmark.\n"
            "Return EXACTLY one line in the form: FINAL ANSWER: <value>\n"
            "Rules:\n"
            "1) After 'FINAL ANSWER:' put only the answer, no explanation.\n"
            "2) For numbers: no thousand separators, no units unless the question explicitly asks for units.\n"
            "3) For text: no extra words. Drop leading articles (a/an/the) UNLESS "
            "the question demands the exact/verbatim wording or all-caps text — "
            "then reproduce it exactly as written in the source.\n"
            "4) For lists: comma-separated, no extra words.\n"
            "5) For yes/no questions: answer exactly 'Yes' or 'No'.\n"
            "6) If the question asks for a quantity in thousands/millions, convert "
            "and round as the question specifies.\n"
            "7) OBEY any explicit formatting instruction stated inside the question "
            "itself (e.g. 'give the city name only', 'answer in caps', 'round to "
            "two decimals') — it overrides the defaults above.\n"
            "CRITICAL: Pay attention to units in the question!\n"
            "- If asked 'how many thousand hours', divide by 1000.\n"
            "- If asked 'how many million dollars', divide by 1,000,000.\n"
            "Output ONLY the one required line."
        ))
        user_msg = HumanMessage(content=(
            f"Question:\n{query}\n\n"
            f"Raw model output:\n{raw}\n\n"
            "Apply the rules and respond with exactly one line."
        ))

        try:
            formatted = llm.invoke([system_msg, user_msg]).content or ""
        except Exception as e:
            print(f"[formatter] LLM call failed: {e}")
            formatted = ""

        # 2) Extract the part after "FINAL ANSWER:" using simple string operations
        lower = formatted.lower()
        marker = "final answer:"
        if marker in lower:
            start = lower.index(marker) + len(marker)
            value = formatted[start:].strip()

            # Deterministic unit fix the LLM formatter often misses: when the
            # question asks for a quantity "in thousands/millions" but the value
            # is still in base units (large number), convert it. Only triggers
            # on clearly-unconverted magnitudes so an already-correct small
            # answer is left untouched.
            ql = (query or "").lower()
            bare = value.replace(",", "").replace(" ", "")
            if re.fullmatch(r"-?\d+(\.\d+)?", bare):
                num = float(bare)
                conv = None
                if "thousand" in ql and abs(num) >= 1000:
                    conv = num / 1000.0
                elif "million" in ql and abs(num) >= 1_000_000:
                    conv = num / 1_000_000.0
                if conv is not None:
                    value = str(int(conv)) if conv == int(conv) else str(conv)

            final_line = f"FINAL ANSWER: {value}"
        else:
            # Minimal fallback to keep interface contract
            final_line = "FINAL ANSWER: "

        # Record final message so process_query can return it
        messages = messages + [AIMessage(content=final_line)]
        return {**state, "messages": messages, "response": final_line, "next": "end"}
    
    def extract_concise_answer(text: str) -> str:
        """Extract a concise answer from the response text"""
        # First look for an explicit "FINAL ANSWER:" pattern already in the text
        import re
        final_answer_match = re.search(r"FINAL ANSWER:\s*([^\n]+)", text)
        if final_answer_match:
            return final_answer_match.group(1).strip()
        
        # If no explicit final answer found, try to extract the last sentence
        sentences = re.split(r'[.!?]\s+', text.strip())
        last_sentence = sentences[-1].strip()
        
        # Clean up the answer - remove common phrases that might precede the answer
        clean_answer = re.sub(r'^(the answer is|therefore|thus|so|hence|in conclusion|we get|we have|result is|answer is|final answer is)\s+', '', last_sentence, flags=re.IGNORECASE)
        
        # Remove any additional explanation after the core answer
        clean_answer = re.split(r'[,.]\s+', clean_answer)[0]
        
        return clean_answer.strip()
    
    # Build the workflow graph
    workflow = StateGraph(WorkflowState)
    
    # Add nodes
    workflow.add_node("router", router)
    workflow.add_node("web_agent", web_agent_node)
    workflow.add_node("video_agent", video_agent_node)
    workflow.add_node("reasoning_agent", reasoning_agent_node)
    workflow.add_node("math_agent", math_agent_node)
    workflow.add_node("creative_agent", creative_agent_node)
    workflow.add_node("general_agent", general_agent_node)
    workflow.add_node("format_response", format_response)
    
    # Add edges from router to appropriate agent
    workflow.add_conditional_edges(
        "router",
        lambda state: state.get("agent_type", AgentType.GENERAL).value,
        {
            AgentType.WEB.value: "web_agent",
            AgentType.VIDEO.value: "video_agent",
            AgentType.REASONING.value: "reasoning_agent",
            AgentType.MATH.value: "math_agent",
            AgentType.CREATIVE.value: "creative_agent",
            AgentType.GENERAL.value: "general_agent"
        }
    )
    
    # Connect all agents to response formatter
    workflow.add_edge("web_agent", "format_response")
    workflow.add_edge("video_agent", "format_response")
    workflow.add_edge("reasoning_agent", "format_response")
    workflow.add_edge("math_agent", "format_response")
    workflow.add_edge("creative_agent", "format_response")
    workflow.add_edge("general_agent", "format_response")
    
    # Add final edge
    workflow.add_conditional_edges(
        "format_response",
        lambda state: state.get("next", "end"),
        {
            "end": END
        }
    )
    
    # Set entry point
    workflow.set_entry_point("router")

    return workflow.compile().with_config({"callbacks": _CALLBACKS})

# Main OptimizedGAAIWorkflow class
class OptimizedGAAIWorkflow:
    def __init__(self):
        """Initialize the optimized GAAI workflow"""
        self.workflow = create_optimized_gaai_workflow()
    
    async def process_query(self, query: str) -> str:
        """
        Process a query using the optimized workflow
        
        Args:
            query: The user's query string
            
        Returns:
            The agent's response
        """
        # Initialize state
        initial_state = {
            "messages": [],
            "query": query,
            "agent_type": None,
            "response": None,
            "intermediate_steps": []
        }

        config = {
            "configurable": {
                # Tạo một ID duy nhất cho mỗi câu query
                "thread_id": str(uuid.uuid4()) 
            },
            # Truyền handler vào đây
            "callbacks": _CALLBACKS
        }
        
        # Execute workflow
        try:
            # Set timeout for the entire workflow
            result = await asyncio.wait_for(
                self.workflow.ainvoke(initial_state, config=config),
                timeout=1500.0  # 1 minute timeout for the entire workflow
            )
            
            # Extract response
            if result and "messages" in result and result["messages"]:
                for msg in reversed(result["messages"]):
                    if isinstance(msg, AIMessage):
                        return msg.content
            
            return result.get("response", "No response generated.")
        except asyncio.TimeoutError:
            return "The request timed out. Please try a simpler query."
        except Exception as e:
            print(f"Error in workflow execution: {str(e)}")
            return f"Error processing query: {str(e)}"

# Example usage
async def main():
    workflow = OptimizedGAAIWorkflow()
    
    # Example queries to test different agent types
    queries = [
        "According to Girls Who Code, how long did it take in years for the percentage of computer scientists that were women to change by 13% from a starting point of 37%?",  # Web agent
        "Solve this logic puzzle: If all roses are flowers and some flowers fade quickly, can we conclude that some roses fade quickly?",  # Reasoning agent
        "Solve the equation: 2x + 5 = 15",  # Math agent
        "Write a short poem about technology and nature."  # Creative agent
    ]
    
    for query in queries:
        print(f"\n\nQuery: {query}")
        response = await workflow.process_query(query)
        print(f"Response: {response}")

if __name__ == "__main__":
    asyncio.run(main())
