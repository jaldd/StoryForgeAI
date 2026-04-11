package ai.storyforge.api.controller;

import ai.storyforge.application.dto.DocumentDto;
import ai.storyforge.application.dto.ProjectDto;
import ai.storyforge.application.port.inbound.ProjectUseCase;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/api/projects")
public class ProjectController {

    private final ProjectUseCase projectUseCase;

    public ProjectController(ProjectUseCase projectUseCase) {
        this.projectUseCase = projectUseCase;
    }

    @GetMapping("/default")
    public ProjectDto getDefaultProject() {
        return projectUseCase.getDefaultProject();
    }

    @GetMapping("/default/documents")
    public List<DocumentDto> getAllDocuments() {
        return projectUseCase.getAllDocuments();
    }

    @GetMapping("/default/chapters")
    public List<DocumentDto> getAllChapters() {
        return projectUseCase.getAllChapters();
    }

    @GetMapping("/default/documents/{documentId}")
    public DocumentDto getDocument(@PathVariable String documentId) {
        return projectUseCase.getDocument(documentId);
    }

    @GetMapping("/default/chapters/{chapterNumber}")
    public DocumentDto getChapter(@PathVariable int chapterNumber) {
        return projectUseCase.getChapter(chapterNumber);
    }

    @PostMapping("/default/reload")
    public void reloadDocuments() {
        projectUseCase.reloadDocuments();
    }
}
