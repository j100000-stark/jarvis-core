import express, { type Express } from "express";
import cors from "cors";
import pinoHttp from "pino-http";
import router from "./routes";
import { logger } from "./lib/logger";
import { redactSecrets } from "./lib/redact";

const app: Express = express();

app.use(
  pinoHttp({
    logger,
    serializers: {
      req(req) {
        return {
          id: req.id,
          method: req.method,
          url: req.url?.split("?")[0],
        };
      },
      res(res) {
        return {
          statusCode: res.statusCode,
        };
      },
    },
  }),
);
app.use(cors());
app.use(express.json({ limit: "64kb" }));
app.use(express.urlencoded({ extended: true, limit: "64kb" }));

app.use("/api", router);

// Global error handler: structured JSON instead of default HTML stack pages;
// never leaks internals (message is logged server-side only).
app.use(
  (err: Error, req: express.Request, res: express.Response, next: express.NextFunction): void => {
    if (res.headersSent) {
      next(err);
      return;
    }
    const status = (err as { status?: number; statusCode?: number }).statusCode
      ?? (err as { status?: number }).status ?? 500;
    const safeMessage = redactSecrets(err.message);
    req.log?.error({ err: safeMessage }, "Unhandled request error");
    res.status(status >= 400 && status < 600 ? status : 500).json({
      error: status === 500 ? "Internal server error." : safeMessage,
      code: status === 500 ? "INTERNAL_ERROR" : "REQUEST_ERROR",
    });
  },
);

export default app;
