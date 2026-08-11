import { Router, type IRouter } from "express";
import healthRouter from "./health";
import jarvisRouter from "./jarvis";

const router: IRouter = Router();

router.use(healthRouter);
router.use(jarvisRouter);

export default router;
