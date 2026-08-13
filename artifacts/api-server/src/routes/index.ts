import { Router, type IRouter } from "express";
import healthRouter from "./health";
import jarvisRouter from "./jarvis";
import ttsRouter from "./tts";

const router: IRouter = Router();

router.use(healthRouter);
router.use(jarvisRouter);
router.use(ttsRouter);

export default router;
