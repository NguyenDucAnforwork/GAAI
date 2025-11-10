from typing import Dict, List, Tuple, Any, Optional
from langgraph.graph import StateGraph
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from llms import openai_llm, gemini_llm, call_llm
from tools.web_tools import web_search_tool
from prompts import WEB_AGENT_SYSTEM_PROMPT

def create_web_agent():
    """Create a web search agent using langgraph"""
    
    # Define the nodes for the graph
    def agent_node(state):
        """Agent thinking node - decides what to do next"""
        messages = state.get("messages", [])
        if not messages:
            messages = [SystemMessage(content=WEB_AGENT_SYSTEM_PROMPT)]
            
        response = openai_llm.invoke(messages)
        
        # Determine if we need to search or can provide an answer
        if "need to search" in response.content.lower() or "let me search" in response.content.lower():
            return {"messages": messages + [response], "next": "search_web"}
        else:
            return {"messages": messages + [response], "next": "end"}
    
    def search_web_node(state):
        """Execute web search"""
        result = web_search_tool(state)
        messages = state.get("messages", [])
        messages.append(AIMessage(content=f"I found this information: {result['web_search_result']}"))
        return {"messages": messages, "next": "process_results"}
    
    def process_results_node(state):
        """Process search results and formulate response"""
        return call_llm(state)
    
    # Build the graph
    workflow = StateGraph(nodes={"agent": agent_node, 
                                "search_web": search_web_node,
                                "process_results": process_results_node})
    
    # Define edges
    workflow.add_edge("agent", "search_web")
    workflow.add_edge("search_web", "process_results")
    workflow.add_edge("process_results", "agent")
    
    # Set entry point
    workflow.set_entry_point("agent")
    
    # Add conditional edges for termination
    workflow.add_conditional_edges(
        "agent",
        lambda state: state.get("next", "agent"),
        {"search_web": "search_web", "end": END}
    )
    
    return workflow.compile()
