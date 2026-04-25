import { Component, ErrorInfo, ReactNode } from "react";
import { AlertTriangle } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
  onError?: (error: Error, errorInfo: ErrorInfo) => void;
}

interface State {
  hasError: boolean;
  error?: Error;
}

/**
 * Error Boundary component that catches JavaScript errors in child components
 * and displays a fallback UI instead of crashing the entire application.
 * 
 * P2/P3 Fix: Ensures one widget failure doesn't crash the entire React app.
 */
export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    // Log error to monitoring service
    console.error("ErrorBoundary caught error:", error, errorInfo);
    this.props.onError?.(error, errorInfo);
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: undefined });
  };

  render() {
    if (this.state.hasError) {
      // Custom fallback UI
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <Card className="border-destructive/30 bg-destructive/5">
          <CardContent className="flex flex-col items-center justify-center gap-4 py-8">
            <AlertTriangle className="h-10 w-10 text-destructive" />
            <div className="text-center">
              <p className="text-sm font-medium text-destructive">
                This widget encountered an error
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {this.state.error?.message || "Unknown error occurred"}
              </p>
            </div>
            <Button 
              variant="outline" 
              size="sm" 
              onClick={this.handleRetry}
              className="mt-2"
            >
              Retry
            </Button>
          </CardContent>
        </Card>
      );
    }

    return this.props.children;
  }
}

/**
 * Wrapper component for dashboard widgets with error boundary
 */
export function WidgetErrorBoundary({ 
  children, 
  title 
}: { 
  children: ReactNode; 
  title?: string;
}) {
  return (
    <ErrorBoundary
      fallback={
        <Card className="border-destructive/30 bg-destructive/5">
          <CardContent className="flex flex-col items-center justify-center gap-3 py-8">
            <AlertTriangle className="h-8 w-8 text-destructive" />
            <p className="text-sm font-medium text-destructive">
              {title ? `${title} failed to load` : "Widget failed to load"}
            </p>
            <p className="text-xs text-muted-foreground">
              The component crashed. Please refresh to retry.
            </p>
          </CardContent>
        </Card>
      }
    >
      {children}
    </ErrorBoundary>
  );
}
