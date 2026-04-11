package ai.storyforge.application.port.inbound;

import reactor.core.publisher.Flux;

public interface WritingAgentUseCase {
    String chat(String message, String projectId);
    Flux<String> chatStream(String message, String projectId);
}
