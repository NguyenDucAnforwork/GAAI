import asyncio
import json
import os
import time
import re
from typing import List, Dict, Any, Tuple
from dotenv import load_dotenv
import re

# Load environment variables
load_dotenv()

# Import the workflow
from langgraph_ver.workflow import OptimizedGAAIWorkflow

def load_metadata(file_path: str) -> List[Dict[str, Any]]:
    """Load metadata from JSONL file"""
    data = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                data.append(json.loads(line))
    return data

def filter_level1_questions(data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filter questions with Level 1"""
    return [item for item in data if item.get("Level") == 1]

def extract_final_answer(response: str) -> str:
    """Extract the final answer from the response"""
    # Simple regex to extract what follows after "FINAL ANSWER:"
    import re
    match = re.search(r"FINAL ANSWER:\s*(.*?)(?:\n|$)", response)
    if match:
        return match.group(1).strip()
    
    # Fallback - return the last line if less than 50 chars
    lines = response.strip().split('\n')
    short_lines = [line.strip() for line in lines if len(line.strip()) < 50]
    if short_lines:
        return short_lines[-1]
    
    return ""

def evaluate_answer(predicted: str, expected: str) -> bool:
    """
    Evaluate if the predicted answer matches the expected answer.
    Performs some normalization to handle formatting variations.
    """
    # Normalize both answers: lowercase, remove extra spaces, punctuation
    def normalize(text: str) -> str:
        # Remove punctuation except for commas in lists
        text = re.sub(r'[^\w\s,]', '', text.lower())
        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        return text
    
    predicted_norm = normalize(predicted)
    expected_norm = normalize(expected)
    
    # If expected is numeric, try extracting just numbers from predicted
    if expected_norm.isdigit():
        numbers = re.findall(r'\d+', predicted_norm)
        if numbers and numbers[0] == expected_norm:
            return True

    # Direct match
    if predicted_norm == expected_norm:
        return True
    
    # Check if the predicted answer contains the expected answer
    if expected_norm in predicted_norm:
        return True
    
    return False

async def test_workflow_accuracy(questions: List[Dict[str, Any]], max_questions: int = 1) -> Tuple[float, List[Dict]]:
    """Test workflow accuracy on given questions"""
    workflow = OptimizedGAAIWorkflow()
    results = []
    correct = 0
    
    # Limit to max_questions
    start_idx = 5
    test_questions = questions[start_idx:max_questions+start_idx]
    
    print(f"Testing {len(test_questions)} Level 1 questions...")
    
    for i, question in enumerate(test_questions):
        question_text = question["Question"]
        expected_answer = question["Final answer"]
        task_id = question["task_id"]
        
        print(f"\n\n===== Question {i+1}/{len(test_questions)} =====")
        print(f"Task ID: {task_id}")
        print(f"Question: {question_text}")
        print(f"Expected answer: {expected_answer}")
        
        start_time = time.time()
        
        try:
            # Process the query
            response = await workflow.process_query(question_text)
            
            # Extract the final answer from the response
            print(f"📝 Full response: {response}")
            predicted_answer = extract_final_answer(response)
            
            # Calculate elapsed time
            elapsed_time = time.time() - start_time
            
            # Check if the answer is correct
            is_correct = evaluate_answer(predicted_answer, expected_answer)
            
            if is_correct:
                correct += 1
                status = "CORRECT"
            else:
                status = "INCORRECT"
                
            print(f"Response ({elapsed_time:.2f}s): {response}")
            print(f"Predicted answer: {predicted_answer}")
            print(f"Status: {status}")
            
            # Save result
            results.append({
                "task_id": task_id,
                "question": question_text,
                "expected": expected_answer,
                "predicted": predicted_answer,
                "response": response,
                "elapsed_time": elapsed_time,
                "is_correct": is_correct
            })
            
            # Add a delay to avoid rate limiting
            await asyncio.sleep(2)
            
        except Exception as e:
            print(f"❌ Error processing question: {str(e)}")
            results.append({
                "task_id": task_id,
                "question": question_text,
                "expected": expected_answer,
                "predicted": None,
                "response": f"Error: {str(e)}",
                "elapsed_time": time.time() - start_time,
                "is_correct": False
            })
    
    # Calculate accuracy
    accuracy = correct / len(test_questions) if test_questions else 0
    
    return accuracy, results

async def main():
    # Path to metadata.jsonl
    metadata_path = os.path.join("test_data", "metadata.jsonl")
    
    # Load and filter data
    all_data = load_metadata(metadata_path)
    level1_questions = filter_level1_questions(all_data)
    
    print(f"Found {len(level1_questions)} Level 1 questions")
    
    # Test workflow accuracy
    accuracy, results = await test_workflow_accuracy(level1_questions)
    
    # Print summary
    print("\n\n===== RESULTS SUMMARY =====")
    print(f"Total questions tested: {len(results)}")
    print(f"Correct answers: {sum(1 for r in results if r.get('is_correct', False))}")
    print(f"Accuracy: {accuracy * 100:.2f}%")
    
    # Save results to file
    from time import time
    import datetime

    # add current timestamp to filename
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = f"results/test_results_{timestamp}.json"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump({
            "accuracy": accuracy,
            "results": results
        }, f, indent=2)
    
    print(f"\nDetailed results saved to {output_path}")

if __name__ == "__main__":
    asyncio.run(main())
