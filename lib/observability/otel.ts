import { NodeSDK } from "@opentelemetry/sdk-node";
import { resourceFromAttributes } from "@opentelemetry/resources";
import {
  ATTR_SERVICE_NAME,
  ATTR_DEPLOYMENT_ENVIRONMENT_NAME,
} from "@opentelemetry/semantic-conventions";
import { getNodeAutoInstrumentations } from "@opentelemetry/auto-instrumentations-node";

let sdk: NodeSDK | undefined;

export function initOtel(): void {
  if (sdk) return;
  sdk = new NodeSDK({
    resource: resourceFromAttributes({
      [ATTR_SERVICE_NAME]: process.env.DD_SERVICE ?? "stock-agent-frontend",
      [ATTR_DEPLOYMENT_ENVIRONMENT_NAME]:
        process.env.DD_ENV ?? process.env.NODE_ENV ?? "development",
    }),
    instrumentations: [getNodeAutoInstrumentations()],
  });
  sdk.start();
}
