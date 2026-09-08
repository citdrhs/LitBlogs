import { capturePasswordResetTokenAtBootstrap } from "./utils/resetToken";
import {
  captureEmailVerificationTokenAtBootstrap,
  clearBootstrappedEmailVerificationToken,
} from "./utils/verificationToken";

capturePasswordResetTokenAtBootstrap();
captureEmailVerificationTokenAtBootstrap();
void import("./main.jsx").catch(clearBootstrappedEmailVerificationToken);
