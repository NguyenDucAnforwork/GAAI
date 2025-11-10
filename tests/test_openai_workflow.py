import asyncio
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Force OpenAI as the only LLM
os.environ["USE_OPENAI_ONLY"] = "TRUE"

# Import after setting environment variable
from langgraph_ver.workflow import OptimizedGAAIWorkflow

async def test_workflow():
    """Test the workflow with OpenAI only"""
    print("Starting workflow test with OpenAI only...")
    
    workflow = OptimizedGAAIWorkflow()
    
    # Test query
    query = "According to the website girlswhocode.com, how long did it take in years for the percentage of computer scientists that were women to change by 13% from a starting point of 37%?"
    print(f"Query: {query}")
    
    # Run the workflow
    response = await workflow.process_query(query)
    print(f"Response: {response}")

if __name__ == "__main__":
    asyncio.run(test_workflow())
