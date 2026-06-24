#!/usr/bin/env python3
"""
Test SmolVLM Video Analysis
"""

import sys
sys.path.append('.')

from langgraph_ver.agents.video_agent_smolvlm import analyze_youtube_video_direct, extract_youtube_url

def test_smolvlm_video():
    """Test SmolVLM video analysis"""
    
    query = "In the video https://www.youtube.com/watch?v=L1vXCYZAYYM, what is the highest number of bird species to be on camera simultaneously?"
    
    print("=" * 60)
    print("🎬 SMOLVLM VIDEO ANALYSIS TEST")
    print("=" * 60)
    print(f"Query: {query}")
    
    # Extract URL
    url = extract_youtube_url(query)
    if not url:
        print("❌ No YouTube URL found in query")
        return
    
    print(f"URL: {url}")
    print("=" * 60)
    
    try:
        # Run analysis
        result = analyze_youtube_video_direct(url, query)
        
        print("\n📋 ANALYSIS RESULT:")
        print("-" * 40)
        print(result)
        
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_smolvlm_video()