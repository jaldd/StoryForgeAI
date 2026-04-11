package ai.storyforge.application.port.outbound;

import reactor.core.publisher.Flux;

public interface ModelGateway {
    String chat(String prompt);
    dev.langchain4j.data.message.AiMessage chat(dev.langchain4j.data.message.UserMessage message);
    Flux<String> chatStream(String prompt);
}
