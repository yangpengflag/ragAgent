import { AlertTriangle } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";

/**
 * 表单级错误展示。
 *
 * 抽出来是为了让各表单只负责编排：错误文案由各 feature 的 `to*Message` 给出，
 * 这里只管呈现（含 `role="alert"`，供断言与读屏）。
 */
export function FormError({ message }: { message: string | null }) {
  if (message === null || message === "") {
    return null;
  }
  return (
    <Alert variant="destructive" data-testid="form-error">
      <AlertTriangle aria-hidden="true" />
      <AlertDescription>{message}</AlertDescription>
    </Alert>
  );
}
