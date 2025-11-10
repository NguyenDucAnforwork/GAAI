#!/usr/bin/env python3
"""
Direct Video Analysis Test
Test video analysis tools directly without going through full workflow
"""

import sys
import os
sys.path.append('.')

from tools.video_tools import video_understanding_enhanced

def test_video_analysis():
    """Test video analysis directly"""
    url = "https://www.youtube.com/watch?v=L1vXCYZAYYM"
    question = "What is the highest number of bird species to be on camera simultaneously?"
    
    print("=" * 60)
    print("🎬 DIRECT VIDEO ANALYSIS TEST")
    print("=" * 60)
    print(f"URL: {url}")
    print(f"Question: {question}")
    print("=" * 60)
    
    try:
        result = video_understanding_enhanced(url, question)
        print("\n📋 RESULT:")
        print(result)
        
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_video_analysis()