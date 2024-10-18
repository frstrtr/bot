import re

def find_mentions_and_links(file_path):
    """
    Find all @username mentions and t.me/ links in a .txt file.

    Args:
        file_path (str): The path to the .txt file.

    Returns:
        dict: A dictionary with two keys 'mentions' and 'links', each containing a list of found items.
    """
    with open(file_path, 'r', encoding='utf-8') as file:
        content = file.read()

    # Regular expression to find @username mentions
    mentions = re.findall(r'@\w+', content)

    # Regular expression to find t.me/ links
    links = re.findall(r'https?://t\.me/\S+', content)

    return {
        'mentions': mentions,
        'links': links
    }

# Example usage
if __name__ == "__main__":
    file_path = 'example.txt'
    results = find_mentions_and_links(file_path)
    print("Mentions:", results['mentions'])
    print("Links:", results['links'])