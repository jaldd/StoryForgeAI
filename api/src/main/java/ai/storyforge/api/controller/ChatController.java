package ai.storyforge.api.controller;

import ai.storyforge.application.dto.ChatRequest;
import ai.storyforge.application.port.inbound.WritingAgentUseCase;
import org.springframework.http.MediaType;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.web.bind.annotation.*;
import reactor.core.publisher.Flux;

@RestController
@RequestMapping("/api")
public class ChatController {

    private final WritingAgentUseCase writingAgentUseCase;

    public ChatController(WritingAgentUseCase writingAgentUseCase) {
        this.writingAgentUseCase = writingAgentUseCase;
    }

    @GetMapping(value = "/chat", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public Flux<ServerSentEvent<String>> chat(@RequestParam("message") String message,
                                              @RequestParam(value = "projectId", required = false) String projectId) {
        return writingAgentUseCase.chatStream(message, projectId)
                .map(token -> ServerSentEvent.<String>builder()
                        .event("token")
                        .data(token)
                        .build())
                .concatWith(Flux.just(
                        ServerSentEvent.<String>builder()
                                .event("done")
                                .data("[DONE]")
                                .build()
                ));
    }

    @PostMapping(value = "/chat/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public Flux<String> chatStream(@RequestBody ChatRequest request) {
        return Flux.just(writingAgentUseCase.chat(request.message(), request.projectId()));
    }
}
