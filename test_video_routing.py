import asyncio
from langgraph_ver.workflow import OptimizedGAAIWorkflow

async def test_video_routing():
    print("Testing VIDEO routing...")
    wf = OptimizedGAAIWorkflow()
    
    # Test query with YouTube URL
    query = "In the video https://www.youtube.com/watch?v=L1vXCYZAYYM, what is the highest number of bird species to be on camera simultaneously?"
    
    try:
        result = await wf.process_query(query)
        print(f"Result: {result}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_video_routing())