import requests
import re
r = requests.get('http://localhost:3000/', timeout=10)
tabs = re.findall(r'<button[^>]*class="tab"[^>]*>([^<]+)</button>', r.text)
print('Tabs found:', tabs)
print('HTML length:', len(r.text))
print('Has tabs container:', 'tabs' in r.text)