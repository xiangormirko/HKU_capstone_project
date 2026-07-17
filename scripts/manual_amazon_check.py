# tests/test_amazon.py
import os
import sys
from pathlib import Path

# 1. Find the project root and the scheduler directory relative to this file
current_file = Path(__file__).resolve()
project_root = current_file.parent.parent
scheduler_dir = project_root / "scheduler"

# 2. Append the 'scheduler' path so Python knows where to find the scraper modules
if str(scheduler_dir) not in sys.path:
    sys.path.append(str(scheduler_dir))

# Load environment variables from the project root
from dotenv import load_dotenv
load_dotenv(dotenv_path=project_root / ".env")

# 3. Import and run the scraper task
try:
    from main_scheduler import task_amazon_apify
    
    print("🚀 Starting direct Amazon Scraper & DB integration test...")
    task_amazon_apify()
    print("\n🎉 Test execution completed! Check your database to see the results.")
    
except ImportError as ie:
    print(f"❌ Import Error: Could not load scraper modules. Details: {ie}")
    print(f"Searched paths: {sys.path}")
except Exception as e:
    print(f"❌ Test failed during execution: {e}")