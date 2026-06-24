import asyncio
import os
import time
import sys
from dotenv import load_dotenv, find_dotenv

# Add environment variable to check API keys
os.environ["DEBUG_API_KEYS"] = "true"

# Load environment variables
load_dotenv(find_dotenv(), override=True)

# Check and display API keys (censored for security)
def display_key_status(key_name):
    key = os.getenv(key_name)
    if not key:
        print(f"⚠️ Warning: {key_name} not found in environment variables")
    else:
        print(f"✓ {key_name}: {'*' * (len(key) - 4) + key[-4:]} (found)")
        
# Check key environment variables
print("Checking API keys:")
display_key_status("OPENAI_API_KEY")
display_key_status("TAVILY_API_KEY")
display_key_status("SERPAPI_API_KEY")
display_key_status("GOOGLE_API_KEY")

# Import the workflow from langgraph implementation
try:
    from langgraph_ver.workflow import OptimizedGAAIWorkflow
    print("✅ Successfully imported OptimizedGAAIWorkflow")
except Exception as e:
    print(f"❌ Error importing workflow: {str(e)}")
    sys.exit(1)

async def test_workflow():
    """Test the OptimizedGAAIWorkflow with various types of queries"""
    print("🚀 Initializing OptimizedGAAIWorkflow...")
    workflow = OptimizedGAAIWorkflow()
    
    # Test queries representing different agent types
    test_queries = [
        # Web agent queries
        "What is the current population of Tokyo?",
        "What were the major tech announcements this week?",
        
        # Reasoning agent queries
        # "If a triangle has sides of length 3, 4, and 5, what is its area?",
        # "In a tournament, each team plays against every other team exactly once. If there are 8 teams, how many matches will be played?",
        
        # # General agent queries
        # "Write a short poem about artificial intelligence",
        # "Explain quantum computing to a 10-year-old"
    ]
    
    for i, query in enumerate(test_queries):
        print(f"\n\n===== Test Query {i+1} =====")
        print(f"Query: {query}")
        
        # Measure response time
        start_time = time.time()
        
        try:
            response = await workflow.process_query(query)
            
            # Calculate elapsed time
            elapsed_time = time.time() - start_time
            
            print(f"Response ({elapsed_time:.2f}s):")
            print(response)
            
        except Exception as e:
            print(f"❌ Error processing query: {str(e)}")

if __name__ == "__main__":
    print("Starting langgraph workflow test...")
    asyncio.run(test_workflow())
    print("\nTest completed!")
