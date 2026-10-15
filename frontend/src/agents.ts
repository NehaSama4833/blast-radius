export const AGENTS = ["Lead", "Changes", "Impact", "History", "People"] as const;
export const COLOR: Record<string, string> = {
  Lead: "#e6edf3", Changes: "#a371f7", Impact: "#f778ba", History: "#58a6ff", People: "#39c5cf",
};
export const ROLE: Record<string, string> = {
  Lead: "ranks suspects, reads the board, decides",
  Changes: "what shipped right before the alerts",
  Impact: "what breaks, who is hit, revenue at risk",
  History: "has this pattern happened before",
  People: "who knows this system and is awake",
};
