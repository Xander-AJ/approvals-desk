import os

from pesa.app import create_app

_key = os.environ.get("SANDBOX_API_KEY")
if not _key and os.environ.get("SANDBOX_INSECURE") != "1":
    raise RuntimeError("set SANDBOX_API_KEY (or SANDBOX_INSECURE=1 for local experiments)")
app = create_app(api_key=_key)

if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=Resource.create({"service.name": "pesa-sandbox"}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"], insecure=os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"].startswith("http://"))))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)
