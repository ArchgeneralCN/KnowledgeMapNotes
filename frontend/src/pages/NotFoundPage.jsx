import { ArrowLeft, Map } from 'lucide-react';
import { Link } from 'react-router-dom';

export default function NotFoundPage() {
  return <main className="not-found"><div className="not-found-art glass"><Map size={34} /><span>404</span></div><span className="eyebrow">LOST NODE</span><h1>这个节点不在图谱里</h1><p>地址可能已变更，或从未被创建。</p><Link className="button primary" to="/home"><ArrowLeft size={17} />返回工作台</Link></main>;
}
