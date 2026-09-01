import logging
import sys
import threading
import time
import traceback

from cecli.decoding import safe_open

# Set up logging to catch asyncio framework logs
logging.basicConfig(level=logging.INFO)
logging.getLogger("asyncio").setLevel(logging.DEBUG)


def dump_stacks_to_file(filename="hang_dump.log", interval=5, max_prints=10):
    """Periodically writes stack traces to a file, resetting it after max_prints."""
    print_count = 0

    while True:
        time.sleep(interval)
        try:
            # Determine mode: "w" to overwrite/clear on the 11th print, "a" to append
            mode = "w" if print_count >= max_prints else "a"

            with safe_open(filename, mode) as f:
                if mode == "w":
                    f.write(f"--- Log reset automatically after {max_prints} prints ---\n")
                    print_count = 0  # Reset the counter

                timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                f.write(
                    f"\n=================== STACK TRACE DUMP ({timestamp}) ===================\n"
                )

                for thread_id, frame in sys._current_frames().items():
                    thread_obj = threading._active.get(thread_id)
                    thread_name = thread_obj.name if thread_obj else "Unknown Thread"

                    f.write(f"\nThread Name: {thread_name} (ID: {thread_id})\n")
                    f.write("-" * 40 + "\n")
                    traceback.print_stack(frame, file=f)

                f.write("=" * 70 + "\n")

            print_count += 1  # Increment after a successful write

        except Exception as e:
            print(f"Error writing stack dump to file: {e}", file=sys.stderr)


# Start the monitor in a background daemon thread
monitor_thread = threading.Thread(
    target=dump_stacks_to_file,
    args=("program_hangs.log", 5, 10),  # Clears every 10 prints
    daemon=True,
)
monitor_thread.start()
