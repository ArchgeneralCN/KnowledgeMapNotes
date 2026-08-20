import { FolderOpen, Home, Settings } from 'lucide-react';

export default function AppSidebar({ active, onHome, onLibrary, onSettings }) {
  const items = [
    { id: 'home', label: '首页', icon: Home, action: onHome },
    { id: 'library', label: '文件库', icon: FolderOpen, action: onLibrary },
  ];
  return (
    <aside className="app-sidebar glass">
      <button className="brand-mark" aria-label="Mapnote 首页" onClick={onHome}>
        <span>M</span>
      </button>
      <nav className="side-nav" aria-label="主导航">
        {items.map(({ id, label, icon: Icon, action }) => (
          <button key={id} className={`nav-button ${active === id ? 'active' : ''}`} onClick={action} data-tooltip={label} aria-label={label}>
            <Icon size={20} strokeWidth={1.8} />
          </button>
        ))}
      </nav>
      <button className="nav-button settings-button" onClick={onSettings} data-tooltip="设置" aria-label="设置">
        <Settings size={20} strokeWidth={1.8} />
      </button>
    </aside>
  );
}
