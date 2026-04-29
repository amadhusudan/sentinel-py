from __future__ import annotations

import time

from sentinel import AsyncLogger, TimeBlock, trace


def main() -> None:
    logger = AsyncLogger()

    # 1. Plain trace — record uses the function name only.
    @trace(logger)
    def slow_function_1() -> str:
        time.sleep(1)
        return "Done 1"

    # 2. Trace with a label — disambiguates traces and groups them by domain term.
    @trace(logger, label="slow_path")
    def slow_function_2() -> str:
        time.sleep(2)
        return "Done 2"

    # 3. Trace at the function level + TimeBlock inside it. Both records carry a label,
    #    making it easy to correlate the outer call with the inner hot section.
    @trace(logger, label="checkout")
    def process_everything() -> None:
        with TimeBlock(logger, label="data_crunching"):
            time.sleep(1.5)

    slow_function_1()
    slow_function_2()
    process_everything()

    logger.shutdown()


if __name__ == "__main__":
    main()
