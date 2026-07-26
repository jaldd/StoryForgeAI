package ai.storyforge.domain.exception;

public class DocumentNotFoundException extends RuntimeException {

    public DocumentNotFoundException(String documentId) {
        super("Document not found: " + documentId);
    }

    public DocumentNotFoundException(Throwable cause) {
        super(cause);
    }
}
