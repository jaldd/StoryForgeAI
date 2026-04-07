package ai.storyforge.bootstrap;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.ComponentScan;

@SpringBootApplication
@ComponentScan(basePackages = "ai.storyforge")
public class StoryForgeApplication {

    public static void main(String[] args) {
        SpringApplication.run(StoryForgeApplication.class, args);
    }
}
