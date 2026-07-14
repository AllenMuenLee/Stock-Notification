import socket

def test_connection(host, port):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        print(f"Attempting to connect to {host}:{port}...")
        result = sock.connect_ex((host, port))
        if result == 0:
            print(f"Successfully connected to {host}:{port}")
        else:
            print(f"Failed to connect to {host}:{port}. Error code: {result}")
        sock.close()
    except Exception as e:
        print(f"Exception when connecting to {host}:{port}: {e}")

if __name__ == "__main__":
    test_connection("google.com", 443)
