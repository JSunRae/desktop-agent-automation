import uiautomation as auto

def main():
    print("Checking uiautomation attributes...")
    for attr in dir(auto):
        if "Walker" in attr:
            print(f"Found: {attr}")

    try:
        print(f"RawViewWalker: {auto.RawViewWalker}")
    except AttributeError:
        print("auto.RawViewWalker not found")

if __name__ == "__main__":
    main()
