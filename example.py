from src.tracer import trace
import time

@trace()
def slow_function_1():
    time.sleep(1)
    return "Done 1"

@trace()
def slow_function_2():
    time.sleep(2)
    return "Done 2"

if __name__ == "__main__":
    print("Running library example...")
    print("calling slow_function_1")
    slow_function_1()
    print("calling slow_function_2")
    slow_function_2()
