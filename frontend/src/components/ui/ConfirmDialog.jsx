import Modal from './Modal.jsx';

export default function ConfirmDialog({ state, onCancel }) {
  if (!state) return null;
  const { title, message, confirmLabel = '确认', danger = false, onConfirm } = state;
  return (
    <Modal
      open
      title={title}
      onClose={onCancel}
      footer={(
        <>
          <button className="button secondary" onClick={onCancel}>取消</button>
          <button className={`button ${danger ? 'danger' : 'primary'}`} onClick={() => { onConfirm?.(); onCancel(); }}>{confirmLabel}</button>
        </>
      )}
    >
      <p className="confirm-copy">{message}</p>
    </Modal>
  );
}
