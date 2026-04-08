export default function({ project, $ }: any) {
  return {
    hooks: {
      "session.created": async () => {
        try {
          await $`bash ./hooks/session-start.sh`;
        } catch { /* hook optional */ }
      },
      "session.idle": async () => {
        try {
          await $`bash ./hooks/session-end.sh`;
        } catch { /* hook optional */ }
      },
      "tool.execute.after": async (event: any) => {
        // Auto-format Python nach Edit/Write
        if (["edit", "write"].includes(event.tool) &&
            event.input?.path?.endsWith(".py")) {
          try {
            await $`ruff format ${event.input.path}`;
          } catch { /* ruff optional */ }
        }
        // Skill-Tracking
        if (event.tool === "skill") {
          try {
            await $`bash ./hooks/skill-track.sh`;
          } catch { /* tracking optional */ }
        }
      }
    }
  };
}
