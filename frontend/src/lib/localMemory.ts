const KEY = 'friday_limited_memory_v1';
const MAX_ITEMS = 80;

interface LocalMemoryItem {
  id: string;
  text: string;
  createdAt: number;
}

function readItems(): LocalMemoryItem[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(KEY) || '[]');
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function writeItems(items: LocalMemoryItem[]) {
  localStorage.setItem(KEY, JSON.stringify(items.slice(-MAX_ITEMS)));
}

function terms(text: string): string[] {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, ' ')
    .split(/\s+/)
    .filter(word => word.length > 2);
}

export function retrieveLocalMemory(query: string, limit = 4): string {
  const queryTerms = new Set(terms(query));
  if (queryTerms.size === 0) return '';
  return readItems()
    .map(item => {
      const score = terms(item.text).reduce((sum, term) => sum + (queryTerms.has(term) ? 1 : 0), 0);
      return { item, score };
    })
    .filter(entry => entry.score > 0)
    .sort((a, b) => b.score - a.score || b.item.createdAt - a.item.createdAt)
    .slice(0, limit)
    .map(entry => `- ${entry.item.text}`)
    .join('\n');
}

export function saveLocalMemory(userText: string, assistantText: string) {
  const text = `User: ${userText.slice(0, 350)}\nAssistant: ${assistantText.slice(0, 550)}`;
  const items = readItems();
  items.push({ id: crypto.randomUUID(), text, createdAt: Date.now() });
  writeItems(items);
}

export function clearLocalMemory() {
  localStorage.removeItem(KEY);
}

