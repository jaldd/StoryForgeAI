package ai.storyforge.domain.model.vo;

import jakarta.persistence.Column;
import jakarta.persistence.Embeddable;
import java.io.Serializable;
import java.util.UUID;

@Embeddable
public record NovelProjectId(@Column(name = "project_uuid") UUID value) implements Serializable {

    public NovelProjectId {
        if (value == null) {
            value = UUID.randomUUID();
        }
    }

    public static NovelProjectId generate() {
        return new NovelProjectId(UUID.randomUUID());
    }

    public static NovelProjectId fromString(String value) {
        return new NovelProjectId(UUID.fromString(value));
    }

    public static NovelProjectId of(String value) {
        return fromString(value);
    }

    public String toStringValue() {
        return value.toString();
    }
}
