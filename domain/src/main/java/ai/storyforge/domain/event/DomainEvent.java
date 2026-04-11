package ai.storyforge.domain.event;

import java.time.LocalDateTime;
import java.util.UUID;

public record DomainEvent(
    UUID eventId,
    String eventType,
    LocalDateTime occurredAt,
    UUID aggregateId
) {
    public DomainEvent(String eventType, UUID aggregateId) {
        this(UUID.randomUUID(), eventType, LocalDateTime.now(), aggregateId);
    }
}
