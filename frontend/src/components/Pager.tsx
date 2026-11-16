export default function Pager({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const from = total === 0 ? 0 : page * pageSize + 1;
  const to = Math.min(total, (page + 1) * pageSize);
  return (
    <div className="pager">
      <span className="num">{from.toLocaleString()}–{to.toLocaleString()} of {total.toLocaleString()}</span>
      <span className="form-row">
        <button className="btn sm" disabled={page <= 0} onClick={() => onPage(page - 1)}>Previous</button>
        <span className="num">Page {page + 1} of {pages}</span>
        <button className="btn sm" disabled={page + 1 >= pages} onClick={() => onPage(page + 1)}>Next</button>
      </span>
    </div>
  );
}
