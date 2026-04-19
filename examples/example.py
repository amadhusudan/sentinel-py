from sentinel.tracer import trace, TimeBlock
from sentinel.logger import AsyncLogger
import time

logger = AsyncLogger()

@trace(logger)
def slow_function_1():
    time.sleep(1)
    return "Done 1"

@trace(logger)
def slow_function_2():
    time.sleep(2)
    return "Done 2"

@trace(logger)
def process_everything():
    # Part 1: Some fast code
    print("Doing fast stuff...")
    
    # Part 2: Time only the specific slow loop
    with TimeBlock(logger, label="data_crunching"):
        time.sleep(1.5)
        print("Crunching complete.")


if __name__ == "__main__":
    print("Running library example...")
    print("calling slow_function_1")
    slow_function_1()
    print("calling slow_function_2")
    slow_function_2()
    print("calling process_everything")
    process_everything()