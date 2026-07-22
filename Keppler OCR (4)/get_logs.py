import subprocess

try:
    result = subprocess.run(["docker", "logs", "--tail", "50", "kepplerocr4-worker-1"], capture_output=True, text=True, check=True)
    with open("worker_logs.txt", "w") as f:
        f.write(result.stdout)
        f.write("\n--- STDERR ---\n")
        f.write(result.stderr)
    print("Logs saved successfully.")
except Exception as e:
    with open("worker_logs.txt", "w") as f:
        f.write(f"Error fetching logs: {e}")
    print("Failed.")
