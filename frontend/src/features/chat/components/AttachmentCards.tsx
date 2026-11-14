import { Icon } from "../../../shared/components/DesignPrimitives";
import { fileSize } from "../model/attachments";

type FileCard = { name: string; media_type: string; size: number; url: string };
export function AttachmentCards({
  files,
  onRemove,
  disabled,
}: {
  files: FileCard[];
  onRemove?: (index: number) => void;
  disabled?: boolean;
}) {
  if (!files.length) return null;
  return (
    <ul
      aria-label={onRemove ? "Attached files" : "Message attachments"}
      className="flex max-w-full flex-wrap gap-space-sm"
    >
      {files.map((file, index) => (
        <li
          key={`${index}-${file.name}`}
          className="flex min-w-0 max-w-full items-center gap-space-sm rounded-lg border border-border-subtle bg-surface-pure p-space-sm text-on-surface md:max-w-64"
        >
          {file.media_type.startsWith("image/") ? (
            <img
              src={file.url}
              alt={`Preview of ${file.name}`}
              className="h-12 w-12 shrink-0 rounded-md object-cover"
            />
          ) : (
            <span className="flex h-12 w-10 shrink-0 items-center justify-center rounded-md bg-secondary-container text-primary">
              <Icon
                name={
                  file.name.endsWith(".xlsx") || file.name.endsWith(".csv")
                    ? "table_chart"
                    : "description"
                }
              />
            </span>
          )}
          <div className="min-w-0 flex-1">
            {onRemove ? (
              <p className="truncate text-body-sm font-bold" title={file.name}>
                {file.name}
              </p>
            ) : (
              <a
                href={file.url}
                download={file.name}
                className="block truncate text-body-sm font-bold underline"
                title={file.name}
              >
                {file.name}
              </a>
            )}
            <p className="text-label-sm text-secondary">
              {fileSize(file.size)} ·{" "}
              {file.name.split(".").pop()?.toUpperCase()}
            </p>
          </div>
          {onRemove && (
            <button
              type="button"
              aria-label={`Remove ${file.name}`}
              onClick={() => onRemove(index)}
              disabled={disabled}
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md hover:bg-surface-container-high disabled:opacity-50"
            >
              <Icon name="close" className="text-[18px]" />
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}
