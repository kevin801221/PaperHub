import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";

import { Button } from "@/components/ui/button";

export function ThemeToggle() {
  const { theme, resolvedTheme, setTheme } = useTheme();
  // resolvedTheme reflects "system" preferences resolved to "light" or "dark"
  const isDark = (resolvedTheme ?? theme) === "dark";
  const Icon = isDark ? Sun : Moon;
  const next = isDark ? "light" : "dark";

  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label={`Switch theme (currently ${isDark ? "dark" : "light"})`}
      onClick={() => setTheme(next)}
    >
      <Icon className="h-4 w-4" />
    </Button>
  );
}
