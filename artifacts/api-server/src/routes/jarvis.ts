import { Router, type IRouter } from "express";
import {
  GetJarvisStatusResponse,
  GetJarvisSystemResponse,
  SendJarvisMessageBody,
  SendJarvisMessageResponse,
} from "@workspace/api-zod";
import {
  getJarvisStatus,
  getJarvisSystemReport,
  sendJarvisGoalJson,
} from "../lib/jarvis-runtime";

const router: IRouter = Router();

router.get("/jarvis/status", (req, res): void => {
  const status = getJarvisStatus();
  if (!status.connected) {
    req.log.warn({ error: status.error }, "JARVIS runtime unavailable");
    res.status(503).json({
      error: status.error ?? "JARVIS runtime is unavailable.",
      code: "RUNTIME_UNAVAILABLE",
    });
    return;
  }
  res.json(GetJarvisStatusResponse.parse(status));
});

router.post("/jarvis/messages", (req, res): void => {
  const parsed = SendJarvisMessageBody.safeParse(req.body);
  if (!parsed.success) {
    req.log.warn({ errors: parsed.error.message }, "Invalid JARVIS goal");
    res.status(400).json({ error: parsed.error.message, code: "INVALID_GOAL" });
    return;
  }

  const result = sendJarvisGoalJson(parsed.data.goal.trim());
  if ("kind" in result) {
    const code =
      result.kind === "brain_unavailable" ? "BRAIN_UNAVAILABLE" : "RUNTIME_UNAVAILABLE";
    req.log.warn({ code }, "JARVIS goal could not be processed");
    res.status(503).json({ error: result.error, code });
    return;
  }

  res.json(SendJarvisMessageResponse.parse(result));
});

router.get("/jarvis/system", (req, res): void => {
  const report = getJarvisSystemReport();
  if ("error" in report) {
    req.log.warn({ error: report.error }, "JARVIS system report unavailable");
    res.status(503).json({ error: report.error, code: "RUNTIME_UNAVAILABLE" });
    return;
  }
  res.json(GetJarvisSystemResponse.parse(report));
});

export default router;
