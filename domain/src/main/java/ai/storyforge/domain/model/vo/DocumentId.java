package ai.storyforge.domain.model.vo;

import jakarta.persistence.Column;
import jakarta.persistence.Embeddable;
import java.io.Serializable;
import java.util.UUID;

@Embeddable
public record DocumentId(@Column(name = "document_id") String value) implements Serializable {

    public DocumentId {
        if (value == null) {
            value = UUID.randomUUID().toString();
        }
    }

    public static DocumentId generate() {
        return new DocumentId(UUID.randomUUID().toString());
    }

    public static DocumentId of(String value) {
        return new DocumentId(value);
    }
}
