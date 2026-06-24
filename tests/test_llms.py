import unittest
from llms.openai import OpenAI
from llms.gemini import Gemini

class TestLLMs(unittest.TestCase):
    def test_openai_initialization(self):
        llm = OpenAI(api_key="test_key", model="gpt-4")
        self.assertEqual(llm.model, "gpt-4")
        self.assertEqual(llm.api_key, "test_key")

    def test_gemini_initialization(self):
        llm = Gemini(api_key="test_key", model="gemini-2.5")
        self.assertEqual(llm.model, "gemini-2.5")
        self.assertEqual(llm.api_key, "test_key")

if __name__ == "__main__":
    unittest.main()