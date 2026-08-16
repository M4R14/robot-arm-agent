// Shared TypeBox schema fragments used by more than one tool.

import { Type } from "typebox";

export const PoseFields = {
  x: Type.Number({ description: "Target end-effector X position, meters" }),
  y: Type.Number({ description: "Target end-effector Y position, meters" }),
  z: Type.Number({ description: "Target end-effector Z position, meters" }),
  roll_deg: Type.Optional(Type.Number({ description: "Target end-effector roll, degrees" })),
  pitch_deg: Type.Optional(Type.Number({ description: "Target end-effector pitch, degrees" })),
  yaw_deg: Type.Optional(Type.Number({ description: "Target end-effector yaw, degrees" })),
};
