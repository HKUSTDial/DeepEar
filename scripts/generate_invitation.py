import sys
from pathlib import Path
import random
import string
import argparse

# Check if running from root or scripts dir
if Path("src").exists():
    sys.path.insert(0, str(Path("src").absolute()))
elif Path("../src").exists():
    sys.path.insert(0, str(Path("../src").absolute()))
else:
    print("Error: Could not find src directory. Please run from project root.")
    sys.exit(1)

from utils.database_manager import DatabaseManager

def generate_code(length=12):
    """Generate a random invitation code"""
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choices(chars, k=length))

def main():
    parser = argparse.ArgumentParser(description="Generate invitation codes for DeepEar")
    parser.add_argument("-n", "--number", type=int, default=1, help="Number of codes to generate")
    parser.add_argument("-l", "--length", type=int, default=12, help="Length of each code")
    parser.add_argument("--prefix", type=str, default="", help="Optional prefix for the code")
    
    args = parser.parse_args()
    
    db = DatabaseManager()
    
    print(f"\nGenerating {args.number} invitation codes...\n")
    print("-" * 40)
    print(f"{'Code':<25} | {'Status':<10}")
    print("-" * 40)
    
    count = 0
    for _ in range(args.number):
        code_suffix = generate_code(args.length)
        code = f"{args.prefix}{code_suffix}" if args.prefix else code_suffix
        
        if db.create_invitation_code(code):
            print(f"{code:<25} | Success")
            count += 1
        else:
            print(f"{code:<25} | Failed (Duplicate?)")
            
    print("-" * 40)
    print(f"\nSuccessfully generated {count} codes.")
    db.close()

if __name__ == "__main__":
    main()
