import { Component, type ReactNode } from 'react';
import { Button, Result } from 'antd';

/** 保留应用外壳；重试时重新挂载个股页的所有子模块。 */
export class StockErrorBoundary extends Component<{ children: ReactNode; onRetry: () => void }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div className="page-scroll stock-page" data-testid="stock-page">
        <section className="panel" role="alert" data-testid="stock-render-error">
          <Result status="error" title="个股页暂时无法显示" subTitle="页面内容加载异常，请重试。"
            extra={<Button onClick={() => {
              this.props.onRetry();
              this.setState({ failed: false });
            }}>重试</Button>} />
        </section>
      </div>
    );
  }
}
